# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The templates of a robot file: Jinja2, sandboxed, with typed results.

A robot file writes its values as templates: a sentence such as
``"Rotating the stage {{ degrees | num }} degrees"`` or a value such as
``"{{ -degrees if direction == 'counter-clockwise' else degrees }}"``.

One rule makes YAML structures work as templates: a string that is a single
``{{ expression }}`` and nothing else keeps the type of the expression (a
number stays a number, a list stays a list); any other string is rendered as
text. ``render`` applies this to every string of a nested dict or list.

The environment is sandboxed and immutable: a template cannot reach Python
internals or change the values it is given. Undefined names are errors, so a
typo in a robot file fails when the file is checked, not on the robot.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Mapping
from typing import Any

import yaml
from jinja2 import StrictUndefined, Undefined, meta
from jinja2 import TemplateError as JinjaTemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment


class TemplateError(Exception):
    """A template of the robot file cannot be compiled or rendered."""


def _num(value: Any) -> str:
    """A number as a person says it: 10.0 is "10", 2.50 is "2.5"."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def _plural(value: Any, word: str, plural: str | None = None) -> str:
    """A count with its word: ``1 | plural('degree')`` is "1 degree", 2.5 is "2.5 degrees"."""
    many = plural if plural is not None else word + "s"
    return f"{_num(value)} {word if value == 1 else many}"


def _flow_yaml(value: Any) -> str:
    """A value as one line of YAML, e.g. ``{deg: -10.0}``: the payload of a StepIt objective."""
    return yaml.safe_dump(value, default_flow_style=True, width=math.inf, sort_keys=False).strip()


def _scalar(value: Any) -> Any:
    """The first item of a list, None for an empty one, the value itself otherwise."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


# rcl_interfaces/msg/ParameterType: the field of ParameterValue that holds each type.
_PARAMETER_FIELDS = {
    1: "bool_value",
    2: "integer_value",
    3: "double_value",
    4: "string_value",
    5: "byte_array_value",
    6: "bool_array_value",
    7: "integer_array_value",
    8: "double_array_value",
    9: "string_array_value",
}


def _param_value(value: Mapping[str, Any] | None) -> Any:
    """The Python value of an rcl_interfaces/msg/ParameterValue; None when not set."""
    if not isinstance(value, Mapping):
        return None
    field = _PARAMETER_FIELDS.get(value.get("type", 0))
    return value.get(field) if field else None


def _ros_parameters(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A mapping of name to value as rcl_interfaces/msg/Parameter messages; None values are left out.

    The type follows the Python value: a float is a double, a list of floats a
    double array. Write ``[shots | float]`` for a parameter that holds a double array.
    """
    parameters = []
    for name, value in values.items():
        if value is None:
            continue
        parameters.append({"name": name, "value": _ros_parameter_value(value)})
    return parameters


def _ros_parameter_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": 1, "bool_value": value}
    if isinstance(value, int):
        return {"type": 2, "integer_value": value}
    if isinstance(value, float):
        return {"type": 3, "double_value": value}
    if isinstance(value, str):
        return {"type": 4, "string_value": value}
    if isinstance(value, (list, tuple)):
        items = list(value)
        if all(isinstance(item, bool) for item in items) and items:
            return {"type": 6, "bool_array_value": items}
        if all(isinstance(item, int) and not isinstance(item, bool) for item in items) and items:
            return {"type": 7, "integer_array_value": items}
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in items):
            return {"type": 8, "double_array_value": [float(item) for item in items]}
        if all(isinstance(item, str) for item in items):
            return {"type": 9, "string_array_value": items}
    raise TypeError(f"no ROS parameter type for {value!r}")


def _bit_or(value: int, mask: int) -> int:
    return int(value) | int(mask)


def _bit_and_not(value: int, mask: int) -> int:
    return int(value) & ~int(mask)


def _finalize(value: Any) -> Any:
    # Every number printed into a text reads as a person says it, without a filter:
    # "Rotating the stage {{ degrees }} degrees" says 10, not 10.0.
    return _num(value) if isinstance(value, float) else value


def _make_environment() -> ImmutableSandboxedEnvironment:
    env = ImmutableSandboxedEnvironment(undefined=StrictUndefined, autoescape=False, finalize=_finalize)
    env.filters.update(
        num=_num,
        plural=_plural,
        flow_yaml=_flow_yaml,
        scalar=_scalar,
        param_value=_param_value,
        ros_parameters=_ros_parameters,
        bit_or=_bit_or,
        bit_and_not=_bit_and_not,
    )
    env.globals.update(zip=zip, abs=abs, min=min, max=max, round=round)
    return env


_ENV = _make_environment()

# A string that is exactly one {{ expression }}, with no other text around it.
_SINGLE_EXPRESSION = re.compile(r"^\s*\{\{(?P<expression>.*?)\}\}\s*$", re.DOTALL)


@functools.lru_cache(maxsize=1024)
def _compile_text(source: str):
    try:
        return _ENV.from_string(source)
    except JinjaTemplateError as exc:
        raise TemplateError(f"{source!r}: {exc}") from exc


@functools.lru_cache(maxsize=1024)
def _compile_expression(source: str):
    try:
        return _ENV.compile_expression(source, undefined_to_none=False)
    except JinjaTemplateError as exc:
        raise TemplateError(f"{source!r}: {exc}") from exc


def _single_expression(text: str) -> str | None:
    match = _SINGLE_EXPRESSION.match(text)
    if match is None:
        return None
    expression = match.group("expression")
    # "{{ a }} and {{ b }}" also matches the pattern: it is text, not one expression.
    if "{{" in expression or "}}" in expression:
        return None
    return expression


def evaluate(expression: str, variables: Mapping[str, Any]) -> Any:
    """Evaluates a bare Jinja2 expression, e.g. ``status == 4``, and returns its value."""
    compiled = _compile_expression(expression)
    try:
        value = compiled(**variables)
        if isinstance(value, Undefined):
            # A bare expression of a missing name returns an Undefined instead of failing.
            value._fail_with_undefined_error()
        return value
    except JinjaTemplateError as exc:
        raise TemplateError(f"{expression!r}: {exc}") from exc
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, ZeroDivisionError) as exc:
        raise TemplateError(f"{expression!r}: {exc}") from exc


def render(value: Any, variables: Mapping[str, Any]) -> Any:
    """Renders every string of a value, nested dicts and lists included.

    A string that is a single ``{{ expression }}`` becomes the value of the
    expression, with its type; any other string is rendered as text.
    """
    if isinstance(value, str):
        expression = _single_expression(value)
        if expression is not None:
            return evaluate(expression, variables)
        if "{{" not in value and "{%" not in value:
            return value
        try:
            return _compile_text(value).render(**variables)
        except JinjaTemplateError as exc:
            raise TemplateError(f"{value!r}: {exc}") from exc
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, ZeroDivisionError) as exc:
            raise TemplateError(f"{value!r}: {exc}") from exc
    if isinstance(value, Mapping):
        # A key may be a template too, e.g. {"{{ setting }}": "{{ value }}"}.
        return {render(key, variables) if isinstance(key, str) else key: render(item, variables)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [render(item, variables) for item in value]
    return value


def check_syntax(value: Any) -> None:
    """Compiles every template of a value, without rendering it: a syntax error fails here."""
    if isinstance(value, str):
        expression = _single_expression(value)
        if expression is not None:
            _compile_expression(expression)
        elif "{{" in value or "{%" in value:
            _compile_text(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            check_syntax(key)
            check_syntax(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            check_syntax(item)


def names_used(value: Any) -> set[str]:
    """The variables that the templates of a value read, nested values included, globals left out."""
    names: set[str] = set()
    if isinstance(value, str):
        expression = _single_expression(value)
        source = "{{ " + expression + " }}" if expression is not None else value
        if "{{" in source or "{%" in source:
            try:
                names |= meta.find_undeclared_variables(_ENV.parse(source))
            except JinjaTemplateError as exc:
                raise TemplateError(f"{value!r}: {exc}") from exc
    elif isinstance(value, Mapping):
        for key, item in value.items():
            names |= names_used(key) | names_used(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            names |= names_used(item)
    return names - set(_ENV.globals)
