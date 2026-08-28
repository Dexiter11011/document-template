"""document-template: Jinja rendering and DOCX style catalogs."""

from document_template.paths import TEMPLATES_DIR, resolve_template
from document_template.profile import TemplateProfile, default_cache_path, export_gost_styles_config
from document_template.substitute import (
    TemplateRenderResult,
    compute_contents_value,
    detect_title_block,
    render_document,
    substitute_markdown,
    title_page_vars_from_context,
)

__all__ = [
    "TEMPLATES_DIR",
    "TemplateProfile",
    "TemplateRenderResult",
    "compute_contents_value",
    "default_cache_path",
    "detect_title_block",
    "export_gost_styles_config",
    "render_document",
    "resolve_template",
    "substitute_markdown",
    "title_page_vars_from_context",
]
