"""Template asset paths."""

from __future__ import annotations

from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = _PKG_ROOT / "templates"
STYLE_SETS_YAML = TEMPLATES_DIR / "style-sets.yaml"


def resolve_template(template_id: str) -> Path:
    """Resolve template_id to a .docx path under the package templates dir."""
    tid = template_id.strip().removesuffix(".docx")
    if not tid or "/" in tid or "\\" in tid or ".." in tid:
        raise FileNotFoundError(f"invalid template_id: {template_id!r}")

    if tid.startswith("templates/"):
        tid = Path(tid).stem

    candidates = [
        TEMPLATES_DIR / "catalogs" / f"{tid}.docx",
        TEMPLATES_DIR / f"{tid}.docx",
        TEMPLATES_DIR / "custom" / f"{tid}.docx",
    ]
    root = TEMPLATES_DIR.resolve()
    for path in candidates:
        resolved = path.resolve()
        if not str(resolved).startswith(str(root)):
            continue
        if resolved.is_file():
            return resolved

    raise FileNotFoundError(f"unknown template_id: {template_id!r}")
