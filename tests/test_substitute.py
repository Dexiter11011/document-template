"""Tests for document-template substitute processor."""

from __future__ import annotations

from document_model.contents_processor import detect_contents_block
from document_template.substitute import compute_contents_value, substitute_markdown

SAMPLE = """\
<!--block:start:contents-->
{{contents}}
<!-- block:end:contents -->
<!--block:start:main-->
# Alpha
## Beta
<!-- block:end:main -->
"""


def test_detect_contents_block():
    assert detect_contents_block(SAMPLE)


def test_compute_contents_value_formats_markdown():
    ctx = {"toc_depth": "2"}
    md, warnings = compute_contents_value(SAMPLE, jinja_context=ctx, toc_depth="2")
    assert "- 1 Alpha" in md
    assert "Beta" in md
    assert warnings == []


def test_substitute_markdown_replaces_contents_token():
    ctx = {"contents": "- 1 Alpha\n  - 1.1 Beta"}
    out, unresolved = substitute_markdown(SAMPLE, jinja_context=ctx)
    assert "{{contents}}" not in out
    assert "- 1 Alpha" in out
    assert unresolved == []
