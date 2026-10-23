# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT

import pytest

from voicebridge.templating import TemplateError, check_syntax, evaluate, render


def test_a_single_expression_keeps_its_type():
    assert render("{{ -degrees }}", {"degrees": 10.0}) == -10.0
    assert render("{{ [shots | float] }}", {"shots": 20}) == [20.0]
    assert render("{{ {} }}", {}) == {}


def test_any_other_string_is_text():
    assert render("Turning {{ degrees }} degrees", {"degrees": 10}) == "Turning 10 degrees"
    assert render("{{ a }} and {{ b }}", {"a": 1, "b": 2}) == "1 and 2"
    assert render("no template", {}) == "no template"


def test_a_float_in_a_text_reads_as_a_person_says_it():
    assert render("{{ x }} degrees", {"x": 10.0}) == "10 degrees"
    assert render("{{ x }} degrees", {"x": 2.5}) == "2.5 degrees"


def test_nested_values_and_keys_are_rendered():
    value = {"{{ name }}": ["{{ a }}", {"b": "x{{ a }}"}], "fixed": 3}
    assert render(value, {"name": "iso", "a": 1}) == {"iso": [1, {"b": "x1"}], "fixed": 3}


def test_plural():
    assert render("{{ 1 | plural('degree') }}", {}) == "1 degree"
    assert render("{{ 1.0 | plural('degree') }}", {}) == "1 degree"
    assert render("{{ 2.5 | plural('millimetre') }}", {}) == "2.5 millimetres"
    assert render("{{ 3 | plural('child', 'children') }}", {}) == "3 children"


def test_flow_yaml_is_the_payload_of_an_objective():
    assert render("{{ payload | flow_yaml }}", {"payload": {"deg": -10.0}}) == "{deg: -10.0}"
    assert render("{{ payload | flow_yaml }}", {"payload": {"mark": "near"}}) == "{mark: near}"


def test_ros_parameters():
    parameters = render("{{ values | ros_parameters }}",
                        {"values": {"a": [1.0], "b": "8", "c": None, "d": True, "e": 3}})
    assert parameters == [
        {"name": "a", "value": {"type": 8, "double_array_value": [1.0]}},
        {"name": "b", "value": {"type": 4, "string_value": "8"}},
        {"name": "d", "value": {"type": 1, "bool_value": True}},
        {"name": "e", "value": {"type": 2, "integer_value": 3}},
    ]


def test_param_value_and_scalar():
    assert evaluate("v | param_value", {"v": {"type": 8, "double_array_value": [2.0]}}) == [2.0]
    assert evaluate("v | param_value | scalar", {"v": {"type": 8, "double_array_value": []}}) is None
    assert evaluate("v | param_value", {"v": {"type": 0}}) is None


def test_bits():
    assert evaluate("x | bit_or(3)", {"x": 4}) == 7
    assert evaluate("x | bit_and_not(3)", {"x": 7}) == 4


def test_an_undefined_name_is_an_error():
    with pytest.raises(TemplateError):
        render("{{ degres }}", {"degrees": 1})


def test_the_sandbox_keeps_python_internals_out():
    with pytest.raises(TemplateError):
        render("{{ ''.__class__.__mro__ }}", {})


def test_a_syntax_error_is_found_without_rendering():
    with pytest.raises(TemplateError):
        check_syntax({"a": ["{{ x + }}"]})
    check_syntax({"{{ k }}": "{{ x }} and {% if y %}y{% endif %}"})
