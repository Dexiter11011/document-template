"""Golden tests for gostdown-style export from temp catalogs."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from document_template.profile import export_gost_styles_config

CATALOG_DOCX = Path(__file__).resolve().parents[2] / "templates" / "temp" / "catalog.docx"


@pytest.fixture
def gost_export() -> dict:
    if not CATALOG_DOCX.is_file():
        pytest.skip("templates/temp/catalog.docx missing")
    with zipfile.ZipFile(CATALOG_DOCX, "r") as z:
        return export_gost_styles_config(z.read("word/styles.xml"), key="gost-type-a")


def test_export_has_53_styles(gost_export: dict):
    assert len(gost_export["styles"]) == 53
    assert gost_export["key"] == "gost-type-a"


def test_normal_style(gost_export: dict):
    normal = gost_export["styles"]["Normal"]
    assert normal["name"] == "Normal"
    assert normal["font"] == "GOST type A"
    assert normal["sizePt"] == 12.0
    assert normal["lineHeight"] == 1.5
    assert normal["align"] == "justify"
    assert normal["firstLineMm"] == 12.51


@pytest.mark.parametrize("heading_id", [f"Heading{i}" for i in range(1, 10)])
def test_heading_styles(gost_export: dict, heading_id: str):
    h = gost_export["styles"][heading_id]
    assert h["font"] == "GOST type A"
    assert h["sizePt"] == 12.0
    assert h["lineHeight"] == 1.5
    assert h["align"] == "justify"
    assert h["firstLineMm"] == 12.51
    assert h["bold"] is True


def test_heading1_name(gost_export: dict):
    assert gost_export["styles"]["Heading1"]["name"] == "heading 1"
