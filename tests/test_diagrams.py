# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The diagrams of the documents: every SVG is rendered from the current version of its source."""

import hashlib
import re
from pathlib import Path

import pytest

DIAGRAMS = Path(__file__).parent.parent / "docs" / "diagrams"
SOURCES = sorted(DIAGRAMS.glob("*.mmd"))


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_svg_is_up_to_date(source):
    svg = source.with_suffix(".svg")
    assert svg.exists(), f"{svg.name} is missing: run bin/render-diagrams.sh"
    match = re.search(r"sha256 ([0-9a-f]{64})", svg.read_text(encoding="utf-8").splitlines()[0])
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert match and match.group(1) == expected, f"{svg.name} is out of date: run bin/render-diagrams.sh"


def test_every_svg_has_a_source():
    orphans = [svg.name for svg in DIAGRAMS.glob("*.svg") if not svg.with_suffix(".mmd").exists()]
    assert not orphans, f"SVGs without a .mmd source: {orphans}"
