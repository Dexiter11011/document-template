"""Template processor: Jinja substitution and contents block handling."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from document_model.contents_processor import (
    build_contents_info,
    detect_contents_block,
    parse_toc_depth,
)

from document_template.jinja_env import AttrDict, render_template

TITLE_PAGE_KEYS = (
    "developer",
    "city",
    "queue",
    "full_is_name",
    "short_is_name",
    "reg_number",
)


def detect_title_block(text: str) -> bool:
    return bool(re.search(r"<!--\s*block:start:title\b", text or "", re.I))


def title_page_vars_from_context(ctx: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in TITLE_PAGE_KEYS:
        val = ctx.get(key)
        if val is None:
            continue
        if isinstance(val, (list, dict)):
            continue
        out[key] = str(val)
    return out


def substitute_markdown(
    text: str,
    *,
    doc_vars: dict[str, str] | None = None,
    project_fragments: dict[str, str] | None = None,
    shared_pools: dict[str, dict[str, str]] | None = None,
    typed: dict[str, str] | None = None,
    jinja_context: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Render GOST-ON / Jinja template against context."""
    if jinja_context is not None:
        ctx = jinja_context
    else:
        doc_vars = doc_vars or {}
        project_fragments = project_fragments or {}
        shared_pools = shared_pools or {}
        project_ns: dict[str, Any] = dict(project_fragments)
        project_ns["lists"] = {}
        project_ns["tables"] = {}
        project_ns["images"] = {}
        project_ns["objects"] = {}
        for path, val in (typed or {}).items():
            parts = path.split(".")
            if len(parts) >= 3 and parts[0] == "project" and parts[1] == "lists":
                items = [
                    re_line[2:].strip() if re_line.startswith("- ") else re_line
                    for re_line in val.splitlines()
                    if re_line.strip()
                ]
                project_ns["lists"][parts[2]] = items
            elif len(parts) >= 3 and parts[0] == "project" and parts[1] == "tables":
                project_ns["tables"][parts[2]] = val
            elif len(parts) >= 3 and parts[0] == "project" and parts[1] == "images":
                project_ns["images"][parts[2]] = val
            elif len(parts) >= 4 and parts[0] == "project" and parts[1] == "objects":
                oid, fk = parts[2], parts[3]
                obj = project_ns["objects"].setdefault(oid, AttrDict(id=oid))
                obj[fk] = val
        shared_ns = {pid: dict(frags) for pid, frags in shared_pools.items()}
        ctx = {
            **doc_vars,
            "project": AttrDict(project_ns),
            "shared": AttrDict(shared_ns),
        }

    return render_template(text, ctx)


def compute_contents_value(
    text: str,
    *,
    jinja_context: dict[str, Any],
    toc_depth: str | int | None = None,
) -> tuple[str, list[str]]:
    """Compute ``{{contents}}`` markdown from headings (two-pass substitution)."""
    if not detect_contents_block(text):
        return "", []
    depth = parse_toc_depth(
        toc_depth if toc_depth is not None else jinja_context.get("toc_depth")
    )
    pass_ctx = dict(jinja_context)
    pass_ctx["contents"] = ""
    first_pass, _ = substitute_markdown(text, jinja_context=pass_ctx)
    info = build_contents_info(first_pass, depth=depth, source_text=text)
    return info.markdown, info.warnings


@dataclass
class TemplateRenderResult:
    substituted: str
    unresolved: list[str] = field(default_factory=list)
    contents_warnings: list[str] = field(default_factory=list)
    contents_meta: dict[str, Any] = field(default_factory=dict)
    contents: str = ""
    has_contents_block: bool = False
    has_title_block: bool = False
    title_page_vars: dict[str, str] = field(default_factory=dict)


def render_document(
    body_md: str,
    context: dict[str, Any],
    *,
    toc_depth: int | str | None = None,
) -> TemplateRenderResult:
    """Full template processor: contents block + Jinja substitution."""
    jinja_context = dict(context)
    depth = parse_toc_depth(
        toc_depth if toc_depth is not None else jinja_context.get("toc_depth")
    )
    contents_warnings: list[str] = []
    contents_md = ""
    if detect_contents_block(body_md):
        contents_md, contents_warnings = compute_contents_value(
            body_md,
            jinja_context=jinja_context,
            toc_depth=depth,
        )
        jinja_context["contents"] = contents_md
    result, unresolved = substitute_markdown(body_md, jinja_context=jinja_context)
    entry_count = 0
    if contents_md:
        entry_count = sum(
            1 for line in contents_md.splitlines() if line.lstrip().startswith("-")
        )
    return TemplateRenderResult(
        substituted=result,
        unresolved=unresolved,
        contents_warnings=contents_warnings,
        contents=contents_md,
        has_contents_block=detect_contents_block(body_md),
        has_title_block=detect_title_block(body_md),
        title_page_vars=title_page_vars_from_context(jinja_context),
        contents_meta={
            "present": detect_contents_block(body_md),
            "depth": depth,
            "entry_count": entry_count,
            "markdown": contents_md,
        },
    )
