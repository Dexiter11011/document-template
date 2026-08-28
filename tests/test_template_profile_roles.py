"""Tests for style role extraction from DOCX templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from document_template.profile import (
    DXA_TO_MM,
    STYLE_ROLE_ROWS,
    TemplateProfile,
    apply_overrides_to_docx,
    parse_style_details,
)


@pytest.fixture
def catalog_docx() -> Path:
    path = Path(__file__).resolve().parents[2] / "templates" / "catalogs" / "gost-type-a.docx"
    if not path.is_file():
        pytest.skip("gost-type-a catalog missing; run scripts/import_style_catalogs.py")
    return path


def test_parse_style_details_has_normal(catalog_docx: Path):
    profile = TemplateProfile.from_docx(catalog_docx)
    profile.defaults["paragraph"] = "Normal"
    details = profile.style_details()
    normal_sid = profile.style_id("Normal")
    assert normal_sid in details
    assert details[normal_sid].font


def test_role_styles_paragraph_uses_normal(catalog_docx: Path):
    profile = TemplateProfile.from_docx(catalog_docx)
    profile.defaults.update({"paragraph": "Normal"})
    roles = profile.role_styles()
    assert len(roles) == 9
    assert roles[0]["role"] == "paragraph"
    assert roles[0]["word_style"] == "Normal"
    assert roles[0]["font"] == "GOST type A"
    assert roles[1]["role"] == "heading_1"


def test_role_styles_merge_overrides(catalog_docx: Path):
    profile = TemplateProfile.from_docx(catalog_docx)
    profile.defaults["paragraph"] = "Normal"
    roles = profile.role_styles({"roles": {"paragraph": {"font": "Arial", "size_pt": 14}}})
    para = next(r for r in roles if r["role"] == "paragraph")
    assert para["font"] == "Arial"
    assert para["size_pt"] == 14


def test_apply_overrides_patches_docx(catalog_docx: Path, tmp_path: Path):
    import shutil
    import zipfile

    dest = tmp_path / "patched.docx"
    shutil.copy2(catalog_docx, dest)
    profile = TemplateProfile.from_docx(dest)
    profile.defaults["paragraph"] = "Normal"
    apply_overrides_to_docx(
        dest,
        profile,
        {"roles": {"paragraph": {"font": "CustomFontX"}}},
    )
    with zipfile.ZipFile(dest, "r") as z:
        styles = z.read("word/styles.xml").decode("utf-8")
    assert "CustomFontX" in styles
