# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The parts of voicebridge import only the parts below them, as docs/ARCHITECTURE.md draws them."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "src" / "voicebridge"

# What each part may import, besides itself.
ALLOWED = {
    "robotfile": set(),
    "safety": {"robotfile"},
    "robot": {"robotfile"},
    "scripted": set(),
    "conversation": {"robotfile", "safety", "robot", "scripted"},
    "llmproxy": {"robotfile", "safety", "scripted"},
    "tools": {"robotfile", "robot", "conversation"},
    "cli": {"robotfile", "safety", "robot", "scripted", "conversation", "llmproxy", "tools"},
}
MODULES = sorted(path for path in PACKAGE.rglob("*.py") if path.name != "__init__.py")


def _part(path: Path) -> str:
    return path.relative_to(PACKAGE).parts[0].removesuffix(".py")


def _imported_parts(path: Path) -> set[str]:
    parts = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        parts |= {name.split(".")[1] for name in names if name.startswith("voicebridge.")}
    return parts


def test_every_module_belongs_to_a_part():
    assert {_part(path) for path in MODULES} == set(ALLOWED)


@pytest.mark.parametrize("path", MODULES, ids=lambda path: str(path.relative_to(PACKAGE)))
def test_a_module_imports_only_the_parts_below_it(path):
    part = _part(path)
    assert _imported_parts(path) - {part} <= ALLOWED[part]
