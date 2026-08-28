"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from document_template.paths import TEMPLATES_DIR


@pytest.fixture
def gost_catalog() -> Path:
    path = TEMPLATES_DIR / "catalogs" / "gost-type-a.docx"
    if not path.is_file():
        pytest.skip("gost-type-a catalog missing in document-template")
    return path
