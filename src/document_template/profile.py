#!/usr/bin/env python3
"""Parse an ESPD DOCX template into a reusable style/numbering profile.

Styles are extracted once into JSON (``templates/espd.styles.json``) and reused
on every build. Re-run extract after changing the DOCX template:

    python3 scripts/template_profile.py extract templates/espd.docx \\
        -o templates/espd.styles.json
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

DXA_TO_MM = 25.4 / (72 * 20)

# UI role rows: (role_key, ru_label, pipeline_default_key)
STYLE_ROLE_ROWS: list[tuple[str, str, str]] = [
    ("paragraph", "Основной текст", "paragraph"),
]
STYLE_ROLE_ROWS.extend(
    (f"heading_{i}", f"Заголовок {i}", f"heading_{i}") for i in range(1, 9)
)

ALIGNMENT_LABELS: dict[str, str] = {
    "left": "Слева",
    "center": "По центру",
    "right": "Справа",
    "both": "По ширине",
    "distribute": "По ширине",
    "justify": "По ширине",
}

WEIGHT_LABELS: dict[str, str] = {
    "normal": "Обычный",
    "bold": "Полужирный",
    "italic": "Курсив",
    "bold_italic": "Полужирный курсив",
}

# Pipeline defaults: MD construct → Word style *name* (resolved via styles_by_name)
PIPELINE_DEFAULTS: dict[str, str] = {
    "heading_1": "heading 1",
    "heading_2": "heading 2",
    "heading_3": "heading 3",
    "heading_4": "heading 4",
    "heading_5": "heading 5",
    "heading_6": "heading 6",
    "heading_7": "heading 7",
    "heading_8": "heading 8",
    "paragraph": "Body Text",
    "paragraph_first": "First Paragraph",
    "list": "Compact",
    "table": "TableStyleGost",
    "code_block": "Source Code",
    "code_inline": "Verbatim Char",
    "toc_title": "heading 1",
    "toc_1": "toc 1",
    "toc_2": "toc 2",
    "toc_3": "toc 3",
    "fallback": "Normal",
}


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class StyleProps:
    font: str | None = None
    size_pt: float | None = None
    weight: str = "normal"
    alignment: str | None = None
    line_spacing: float | None = None
    indent_mm: float | None = None
    style_id: str | None = None
    style_name: str | None = None

    def to_dict(self) -> dict:
        return {
            "font": self.font,
            "size_pt": self.size_pt,
            "weight": self.weight,
            "weight_label": WEIGHT_LABELS.get(self.weight, self.weight),
            "alignment": self.alignment,
            "alignment_label": ALIGNMENT_LABELS.get(self.alignment or "", self.alignment),
            "line_spacing": self.line_spacing,
            "line_spacing_label": (
                f"×{self.line_spacing:g}" if self.line_spacing is not None else None
            ),
            "indent_mm": self.indent_mm,
            "indent_label": (
                f"{self.indent_mm:.2f} мм" if self.indent_mm is not None else None
            ),
            "style_id": self.style_id,
            "style_name": self.style_name,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "StyleProps":
        if not data:
            return cls()
        return cls(
            font=data.get("font"),
            size_pt=data.get("size_pt"),
            weight=str(data.get("weight") or "normal"),
            alignment=data.get("alignment"),
            line_spacing=data.get("line_spacing"),
            indent_mm=data.get("indent_mm"),
            style_id=data.get("style_id"),
            style_name=data.get("style_name"),
        )

    def merge(self, other: "StyleProps") -> "StyleProps":
        return StyleProps(
            font=other.font if other.font is not None else self.font,
            size_pt=other.size_pt if other.size_pt is not None else self.size_pt,
            weight=other.weight if other.weight != "normal" or self.weight == "normal" else self.weight,
            alignment=other.alignment if other.alignment is not None else self.alignment,
            line_spacing=(
                other.line_spacing if other.line_spacing is not None else self.line_spacing
            ),
            indent_mm=other.indent_mm if other.indent_mm is not None else self.indent_mm,
            style_id=other.style_id or self.style_id,
            style_name=other.style_name or self.style_name,
        )


def _bool_val(el: ET.Element | None, default: bool = False) -> bool:
    if el is None:
        return default
    val = el.get(f"{W}val")
    if val is None:
        return True
    return val not in {"0", "false", "off"}


def _int_attr(el: ET.Element | None, attr: str) -> int | None:
    if el is None:
        return None
    raw = el.get(f"{W}{attr}")
    if raw is None or not str(raw).lstrip("-").isdigit():
        return None
    return int(raw)


def _parse_weight(rpr: ET.Element | None) -> str:
    if rpr is None:
        return "normal"
    bold = _bool_val(rpr.find(f"{W}b"))
    italic = _bool_val(rpr.find(f"{W}i"))
    if bold and italic:
        return "bold_italic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "normal"


def _parse_font(rpr: ET.Element | None, doc_defaults: StyleProps) -> str | None:
    if rpr is not None:
        fonts = rpr.find(f"{W}rFonts")
        if fonts is not None:
            for key in ("ascii", "hAnsi"):
                val = fonts.get(f"{W}{key}")
                if val:
                    return val
            # eastAsia-only is often a CJK fallback; inherit western font from basedOn
        return None
    return doc_defaults.font


def _parse_size_pt(rpr: ET.Element | None) -> float | None:
    if rpr is None:
        return None
    sz = rpr.find(f"{W}sz")
    if sz is None:
        return None
    val = _int_attr(sz, "val")
    if val is None:
        return None
    return val / 2.0


def _parse_alignment(ppr: ET.Element | None) -> str | None:
    if ppr is None:
        return None
    jc = ppr.find(f"{W}jc")
    if jc is None:
        return None
    return jc.get(f"{W}val")


def _parse_line_spacing(ppr: ET.Element | None) -> float | None:
    if ppr is None:
        return None
    sp = ppr.find(f"{W}spacing")
    if sp is None:
        return None
    line = _int_attr(sp, "line")
    if line is None:
        return None
    rule = sp.get(f"{W}lineRule") or "auto"
    if rule == "auto":
        return round(line / 240.0, 2)
    if rule in {"exact", "atLeast"} and line:
        # approximate as multiplier vs 12pt default
        return round(line / 240.0, 2)
    return round(line / 240.0, 2)


def _parse_indent_mm(ppr: ET.Element | None) -> float | None:
    if ppr is None:
        return None
    ind = ppr.find(f"{W}ind")
    if ind is None:
        return None
    first = _int_attr(ind, "firstLine")
    if first is None:
        first = _int_attr(ind, "firstLineChars")
        if first is not None:
            # 100ths of character width — rough fallback
            first = int(first * 2.4)
    if first is None:
        return None
    return round(first * DXA_TO_MM, 2)


def _parse_doc_defaults(styles_root: ET.Element) -> StyleProps:
    defaults = styles_root.find(f"{W}docDefaults")
    if defaults is None:
        return StyleProps()
    rpr = defaults.find(f"{W}rPrDefault") or defaults
    rpr = rpr.find(f"{W}rPr") if rpr is not None else None
    ppr_default = defaults.find(f"{W}pPrDefault")
    ppr = ppr_default.find(f"{W}pPr") if ppr_default is not None else None
    base = StyleProps()
    return StyleProps(
        font=_parse_font(rpr, base),
        size_pt=_parse_size_pt(rpr),
        weight=_parse_weight(rpr),
        alignment=_parse_alignment(ppr),
        line_spacing=_parse_line_spacing(ppr),
        indent_mm=_parse_indent_mm(ppr),
    )


def _style_ref(st: ET.Element, tag: str) -> str | None:
    """Read ``<w:tag w:val="..."/>`` child reference on a style element."""
    el = st.find(f"{W}{tag}")
    if el is None:
        return None
    val = el.get(f"{W}val")
    return val if val else None


def _merge_linked_char_props(
    props: StyleProps,
    st: ET.Element,
    *,
    resolved: dict[str, StyleProps],
) -> StyleProps:
    """Apply bold/italic from linked character style (w:link) to paragraph props."""
    link_id = _style_ref(st, "link")
    if not link_id or link_id not in resolved:
        return props
    linked = resolved[link_id]
    weight = props.weight
    if linked.weight == "bold_italic":
        weight = "bold_italic"
    elif linked.weight == "bold":
        weight = "bold_italic" if weight == "italic" else "bold"
    elif linked.weight == "italic":
        weight = "bold_italic" if weight == "bold" else "italic"
    if weight == props.weight:
        return props
    return StyleProps(
        font=props.font,
        size_pt=props.size_pt,
        weight=weight,
        alignment=props.alignment,
        line_spacing=props.line_spacing,
        indent_mm=props.indent_mm,
        style_id=props.style_id,
        style_name=props.style_name,
    )


def _find_normal_style_id(raw: dict[str, StyleProps]) -> str | None:
    for sid, props in raw.items():
        if sid == "Normal" or (props.style_name or "").casefold() == "normal":
            return sid
    return None


def _apply_implicit_based_on(
    raw: dict[str, StyleProps],
    based_on: dict[str, str],
    *,
    normal_sid: str | None,
) -> None:
    """Word catalog styles often omit w:basedOn; inherit from Normal when missing."""
    if not normal_sid or normal_sid not in raw:
        return
    for sid in raw:
        if sid == normal_sid:
            continue
        if sid not in based_on:
            based_on[sid] = normal_sid


def parse_style_details(styles_xml: bytes) -> dict[str, StyleProps]:
    """Parse ``word/styles.xml`` into resolved paragraph style properties by styleId."""
    if not styles_xml:
        return {}
    root = ET.fromstring(styles_xml)
    doc_defaults = _parse_doc_defaults(root)
    raw: dict[str, StyleProps] = {}
    based_on: dict[str, str] = {}

    for st in root.findall(f"{W}style"):
        sid = st.get(f"{W}styleId")
        if not sid:
            continue
        typ = st.get(f"{W}type") or ""
        if typ and typ != "paragraph":
            continue
        name_el = st.find(f"{W}name")
        name = name_el.get(f"{W}val") if name_el is not None else ""
        ppr = st.find(f"{W}pPr")
        rpr = st.find(f"{W}rPr")
        props = StyleProps(
            font=_parse_font(rpr, doc_defaults),
            size_pt=_parse_size_pt(rpr) or (doc_defaults.size_pt if rpr is None else None),
            weight=_parse_weight(rpr) if rpr is not None else doc_defaults.weight,
            alignment=_parse_alignment(ppr) if ppr is not None else doc_defaults.alignment,
            line_spacing=_parse_line_spacing(ppr) if ppr is not None else doc_defaults.line_spacing,
            indent_mm=_parse_indent_mm(ppr) if ppr is not None else doc_defaults.indent_mm,
            style_id=sid,
            style_name=name,
        )
        raw[sid] = props
        parent = _style_ref(st, "basedOn")
        if parent:
            based_on[sid] = parent

    _apply_implicit_based_on(raw, based_on, normal_sid=_find_normal_style_id(raw))

    resolved: dict[str, StyleProps] = {}

    def resolve(sid: str, seen: set[str] | None = None) -> StyleProps:
        if sid in resolved:
            return resolved[sid]
        seen = seen or set()
        if sid in seen:
            return raw.get(sid, StyleProps(style_id=sid))
        seen.add(sid)
        base = StyleProps()
        parent_id = based_on.get(sid)
        if parent_id and parent_id in raw:
            base = resolve(parent_id, seen)
        own = raw.get(sid, StyleProps(style_id=sid))
        merged = base.merge(own)
        merged.style_id = sid
        if not merged.style_name:
            merged.style_name = own.style_name
        resolved[sid] = merged
        return merged

    for sid in raw:
        resolve(sid)

    for st in root.findall(f"{W}style"):
        sid = st.get(f"{W}styleId")
        if not sid or sid not in resolved:
            continue
        if (st.get(f"{W}type") or "") != "paragraph":
            continue
        resolved[sid] = _merge_linked_char_props(resolved[sid], st, resolved=resolved)

    return resolved


def _align_to_gost(alignment: str | None) -> str | None:
    if not alignment:
        return None
    if alignment in {"both", "distribute", "justify"}:
        return "justify"
    return alignment


def _dxa_to_pt(dxa: int) -> float:
    return round(dxa / 20.0, 3)


def _parse_color(rpr: ET.Element | None) -> str | None:
    if rpr is None:
        return None
    color_el = rpr.find(f"{W}color")
    if color_el is None:
        return None
    val = color_el.get(f"{W}val")
    if not val or val.lower() in {"auto", "000000"}:
        return None
    return val if val.startswith("#") else f"#{val}"


def _parse_spacing_export(ppr: ET.Element | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if ppr is None:
        return out
    sp = ppr.find(f"{W}spacing")
    if sp is None:
        return out
    before = _int_attr(sp, "before")
    after = _int_attr(sp, "after")
    if before is not None:
        out["spaceBeforePt"] = _dxa_to_pt(before)
    if after is not None:
        out["spaceAfterPt"] = _dxa_to_pt(after)
    line_height = _parse_line_spacing(ppr)
    if line_height is not None:
        out["lineHeight"] = line_height
    return out


def _parse_indents_export(ppr: ET.Element | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if ppr is None:
        return out
    ind = ppr.find(f"{W}ind")
    if ind is None:
        return out
    first = _int_attr(ind, "firstLine")
    if first is not None:
        out["firstLineMm"] = round(first * DXA_TO_MM, 2)
    hanging = _int_attr(ind, "hanging")
    if hanging is not None:
        out["hangingMm"] = round(hanging * DXA_TO_MM, 2)
    left = _int_attr(ind, "left")
    if left is not None:
        out["indentLeftMm"] = round(left * DXA_TO_MM, 2)
    return out


def _style_props_from_element(
    st: ET.Element,
    doc_defaults: StyleProps,
) -> StyleProps:
    name_el = st.find(f"{W}name")
    name = name_el.get(f"{W}val") if name_el is not None else ""
    sid = st.get(f"{W}styleId") or ""
    ppr = st.find(f"{W}pPr")
    rpr = st.find(f"{W}rPr")
    return StyleProps(
        font=_parse_font(rpr, doc_defaults),
        size_pt=_parse_size_pt(rpr) or (doc_defaults.size_pt if rpr is None else None),
        weight=_parse_weight(rpr) if rpr is not None else doc_defaults.weight,
        alignment=_parse_alignment(ppr) if ppr is not None else doc_defaults.alignment,
        line_spacing=_parse_line_spacing(ppr) if ppr is not None else doc_defaults.line_spacing,
        indent_mm=_parse_indent_mm(ppr) if ppr is not None else doc_defaults.indent_mm,
        style_id=sid,
        style_name=name,
    )


def _gost_entry_from_style(
    st: ET.Element,
    props: StyleProps,
) -> dict[str, object]:
    typ = st.get(f"{W}type") or "paragraph"
    ppr = st.find(f"{W}pPr")
    rpr = st.find(f"{W}rPr")
    entry: dict[str, object] = {
        "name": props.style_name or props.style_id or "",
    }
    if props.size_pt is not None:
        entry["sizePt"] = props.size_pt
    entry.update(_parse_spacing_export(ppr))
    if props.line_spacing is not None and "lineHeight" not in entry:
        entry["lineHeight"] = props.line_spacing
    if props.font:
        entry["font"] = props.font
    if typ == "paragraph":
        align = _align_to_gost(props.alignment)
        if align:
            entry["align"] = align
        entry.update(_parse_indents_export(ppr))
        if props.indent_mm is not None and "firstLineMm" not in entry:
            entry["firstLineMm"] = props.indent_mm
    if props.weight in {"bold", "bold_italic"}:
        entry["bold"] = True
    if props.weight in {"italic", "bold_italic"}:
        entry["italic"] = True
    color = _parse_color(rpr)
    if color:
        entry["color"] = color
    return entry


def _export_doc_defaults_gost(styles_root: ET.Element) -> dict[str, float]:
    doc_defaults = _parse_doc_defaults(styles_root)
    ppr_default = styles_root.find(f"{W}pPrDefault")
    ppr = ppr_default.find(f"{W}pPr") if ppr_default is not None else None
    spacing = _parse_spacing_export(ppr)
    out: dict[str, float] = {}
    if doc_defaults.size_pt is not None:
        out["sizePt"] = doc_defaults.size_pt
    if spacing.get("spaceAfterPt") is not None:
        out["spaceAfterPt"] = spacing["spaceAfterPt"]
    line_height = spacing.get("lineHeight") or doc_defaults.line_spacing
    if line_height is not None:
        out["lineHeight"] = line_height
    return out


def export_gost_styles_config(
    styles_xml: bytes,
    *,
    key: str,
    profile: "TemplateProfile | None" = None,
    role_overrides: dict | None = None,
) -> dict[str, object]:
    """Export catalog styles in gostdown-compatible JSON (styles + docDefaults + key)."""
    if not styles_xml:
        return {"styles": {}, "docDefaults": {}, "key": key}
    root = ET.fromstring(styles_xml)
    doc_defaults = _parse_doc_defaults(root)
    raw: dict[str, StyleProps] = {}
    elements: dict[str, ET.Element] = {}
    based_on: dict[str, str] = {}

    for st in root.findall(f"{W}style"):
        sid = st.get(f"{W}styleId")
        if not sid:
            continue
        typ = st.get(f"{W}type") or ""
        if typ not in {"paragraph", "character"}:
            continue
        elements[sid] = st
        raw[sid] = _style_props_from_element(st, doc_defaults)
        parent = _style_ref(st, "basedOn")
        if parent:
            based_on[sid] = parent

    _apply_implicit_based_on(raw, based_on, normal_sid=_find_normal_style_id(raw))

    resolved_props: dict[str, StyleProps] = {}

    def resolve_props(sid: str, seen: set[str] | None = None) -> StyleProps:
        if sid in resolved_props:
            return resolved_props[sid]
        seen = seen or set()
        if sid in seen:
            return raw.get(sid, StyleProps(style_id=sid))
        seen.add(sid)
        base = StyleProps()
        parent_id = based_on.get(sid)
        if parent_id and parent_id in raw:
            base = resolve_props(parent_id, seen)
        own = raw.get(sid, StyleProps(style_id=sid))
        merged = base.merge(own)
        merged.style_id = sid
        if not merged.style_name:
            merged.style_name = own.style_name
        resolved_props[sid] = merged
        return merged

    for sid in raw:
        resolve_props(sid)

    for sid, st in elements.items():
        if (st.get(f"{W}type") or "") == "paragraph" and sid in resolved_props:
            resolved_props[sid] = _merge_linked_char_props(
                resolved_props[sid], st, resolved=resolved_props
            )

    styles: dict[str, dict[str, object]] = {}
    for sid, st in elements.items():
        props = resolved_props[sid]
        styles[sid] = _gost_entry_from_style(st, props)

    if profile and role_overrides:
        roles = role_overrides if isinstance(role_overrides, dict) else {}
        for role_key, override in roles.items():
            if not isinstance(override, dict):
                continue
            pipeline_key = role_key
            for rk, _, pk in STYLE_ROLE_ROWS:
                if rk == role_key:
                    pipeline_key = pk
                    break
            style_name = profile.defaults.get(pipeline_key)
            if not style_name:
                continue
            try:
                sid = profile.style_id(style_name)
            except KeyError:
                continue
            entry = styles.get(sid)
            if entry is None:
                continue
            if override.get("font"):
                entry["font"] = override["font"]
            if override.get("size_pt") is not None:
                entry["sizePt"] = float(override["size_pt"])
            weight = override.get("weight")
            if weight:
                entry["bold"] = weight in {"bold", "bold_italic"}
                entry["italic"] = weight in {"italic", "bold_italic"}
                if weight == "normal":
                    entry.pop("bold", None)
                    entry.pop("italic", None)
            if override.get("alignment"):
                align = _align_to_gost(str(override["alignment"]))
                if align:
                    entry["align"] = align
            if override.get("line_spacing") is not None:
                entry["lineHeight"] = float(override["line_spacing"])
            if override.get("indent_mm") is not None:
                entry["firstLineMm"] = float(override["indent_mm"])

    return {
        "styles": styles,
        "docDefaults": _export_doc_defaults_gost(root),
        "key": key,
    }


def apply_overrides_to_docx(docx_path: Path, profile: "TemplateProfile", overrides: dict) -> None:
    """Patch ``word/styles.xml`` inside a DOCX for role-based overrides."""
    roles = overrides.get("roles") if isinstance(overrides, dict) else None
    if not roles:
        return
    import zipfile

    docx_path = docx_path.resolve()
    with zipfile.ZipFile(docx_path, "r") as zin:
        parts = {n: zin.read(n) for n in zin.namelist()}
    styles_xml = parts.get("word/styles.xml")
    if not styles_xml:
        return
    root = ET.fromstring(styles_xml)
    style_index = {st.get(f"{W}styleId"): st for st in root.findall(f"{W}style") if st.get(f"{W}styleId")}

    for role_key, override in roles.items():
        if not isinstance(override, dict):
            continue
        pipeline_key = role_key
        for rk, _, pk in STYLE_ROLE_ROWS:
            if rk == role_key:
                pipeline_key = pk
                break
        style_name = profile.defaults.get(pipeline_key)
        if not style_name:
            continue
        try:
            sid = profile.style_id(style_name)
        except KeyError:
            continue
        st = style_index.get(sid)
        if st is None:
            continue
        ppr = st.find(f"{W}pPr")
        if ppr is None:
            ppr = ET.SubElement(st, f"{W}pPr")
        rpr = st.find(f"{W}rPr")
        if rpr is None:
            rpr = ET.SubElement(st, f"{W}rPr")

        if override.get("font"):
            fonts = rpr.find(f"{W}rFonts")
            if fonts is None:
                fonts = ET.SubElement(rpr, f"{W}rFonts")
            font = str(override["font"])
            for key in ("ascii", "hAnsi", "cs"):
                fonts.set(f"{W}{key}", font)
        if override.get("size_pt") is not None:
            half = int(round(float(override["size_pt"]) * 2))
            for tag in ("sz", "szCs"):
                el = rpr.find(f"{W}{tag}")
                if el is None:
                    el = ET.SubElement(rpr, f"{W}{tag}")
                el.set(f"{W}val", str(half))
        weight = override.get("weight")
        if weight:
            for tag, on in (
                ("b", weight in {"bold", "bold_italic"}),
                ("i", weight in {"italic", "bold_italic"}),
            ):
                el = rpr.find(f"{W}{tag}")
                if on:
                    if el is None:
                        ET.SubElement(rpr, f"{W}{tag}")
                elif el is not None:
                    rpr.remove(el)
        if override.get("alignment"):
            jc = ppr.find(f"{W}jc")
            if jc is None:
                jc = ET.SubElement(ppr, f"{W}jc")
            jc.set(f"{W}val", str(override["alignment"]))
        if override.get("line_spacing") is not None:
            sp = ppr.find(f"{W}spacing")
            if sp is None:
                sp = ET.SubElement(ppr, f"{W}spacing")
            line_val = int(round(float(override["line_spacing"]) * 240))
            sp.set(f"{W}line", str(line_val))
            sp.set(f"{W}lineRule", "auto")
        if override.get("indent_mm") is not None:
            ind = ppr.find(f"{W}ind")
            if ind is None:
                ind = ET.SubElement(ppr, f"{W}ind")
            dxa = int(round(float(override["indent_mm"]) / DXA_TO_MM))
            ind.set(f"{W}firstLine", str(dxa))

    parts["word/styles.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(docx_path, "w") as zout:
        for name, data in parts.items():
            zout.writestr(name, data)


def _add_ru_aliases(styles_by_name: dict[str, str]) -> None:
    for i in range(1, 10):
        en = f"heading {i}"
        ru = f"Заголовок {i}"
        if en in styles_by_name:
            styles_by_name.setdefault(ru, styles_by_name[en])
    if "Title" in styles_by_name:
        styles_by_name.setdefault("Заголовок", styles_by_name["Title"])


@dataclass
class TemplateProfile:
    """Style and numbering snapshot extracted from a DOCX shell/reference."""

    path: Path
    styles_by_name: dict[str, str] = field(default_factory=dict)  # name → styleId
    styles_by_id: dict[str, str] = field(default_factory=dict)  # styleId → name
    styles_meta: list[dict[str, str]] = field(default_factory=list)  # full inventory
    defaults: dict[str, str] = field(default_factory=lambda: dict(PIPELINE_DEFAULTS))
    numbering_xml: bytes = b""
    max_num_id: int = 0
    bullet_abstract_num_id: str = "0"
    decimal_abstract_num_id: str = "1"
    source_sha256: str = ""
    cache_path: Path | None = None
    parts: dict[str, bytes] = field(default_factory=dict, repr=False)
    _style_details: dict[str, StyleProps] | None = field(default=None, repr=False)

    def style_details(self) -> dict[str, StyleProps]:
        if self._style_details is not None:
            return self._style_details
        styles_xml = self.parts.get("word/styles.xml")
        if styles_xml is None and self.path.is_file():
            with zipfile.ZipFile(self.path, "r") as z:
                styles_xml = z.read("word/styles.xml")
        self._style_details = parse_style_details(styles_xml or b"")
        return self._style_details

    def role_styles(self, overrides: dict | None = None) -> list[dict]:
        """Resolved UI role rows with optional user overrides merged in."""
        details = self.style_details()
        role_overrides = (overrides or {}).get("roles") or {}
        rows: list[dict] = []
        for role_key, label, pipeline_key in STYLE_ROLE_ROWS:
            style_name = self.defaults.get(pipeline_key, "")
            props = StyleProps(style_name=style_name)
            try:
                sid = self.style_id(style_name)
                props = details.get(sid, props)
                props.style_id = sid
                props.style_name = style_name
            except KeyError:
                pass
            ov = role_overrides.get(role_key)
            if isinstance(ov, dict):
                props = props.merge(StyleProps.from_dict(ov))
            row = props.to_dict()
            row["role"] = role_key
            row["label"] = label
            row["word_style"] = style_name
            rows.append(row)
        return rows

    def compare_roles(
        self, other: "TemplateProfile", *, other_overrides: dict | None = None
    ) -> list[dict]:
        left = {r["role"]: r for r in self.role_styles()}
        right = {r["role"]: r for r in other.role_styles(other_overrides)}
        diffs: list[dict] = []
        for role_key, label, _ in STYLE_ROLE_ROWS:
            a = left.get(role_key, {})
            b = right.get(role_key, {})
            fields = ("font", "size_pt", "weight", "alignment", "line_spacing", "indent_mm")
            changed = [f for f in fields if a.get(f) != b.get(f)]
            if changed:
                diffs.append(
                    {
                        "role": role_key,
                        "label": label,
                        "fields": changed,
                        "left": a,
                        "right": b,
                    }
                )
        return diffs

    def style_id(self, name: str, default: str | None = None) -> str:
        """Resolve Word style *name* to styleId (never hardcode numeric ids)."""
        if name in self.styles_by_name:
            return self.styles_by_name[name]
        lower = {k.casefold(): v for k, v in self.styles_by_name.items()}
        if name.casefold() in lower:
            return lower[name.casefold()]
        if default is not None:
            return default
        raise KeyError(f"style {name!r} not found in {self.path}")

    def has_style(self, name: str) -> bool:
        try:
            self.style_id(name)
            return True
        except KeyError:
            return False

    def default_style_id(self, key: str, fallback_name: str | None = None) -> str:
        """Resolve a pipeline default key (e.g. ``heading_1``) to styleId."""
        name = self.defaults.get(key) or fallback_name or self.defaults.get("fallback", "Normal")
        return self.style_id(name, default=self.style_id("Normal", default="a0"))

    def next_num_id(self) -> int:
        self.max_num_id += 1
        return self.max_num_id

    def to_dict(self) -> dict:
        """Serializable profile (no DOCX binary parts / numbering.xml)."""
        root = Path(__file__).resolve().parents[1]
        try:
            docx_ref = str(self.path.resolve().relative_to(root))
        except ValueError:
            docx_ref = str(self.path)
        return {
            "version": 1,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": {
                "docx": docx_ref,
                "sha256": self.source_sha256 or (
                    _file_sha256(self.path) if self.path.is_file() else ""
                ),
            },
            "numbering": {
                "max_num_id": self.max_num_id,
                "bullet_abstract_num_id": self.bullet_abstract_num_id,
                "decimal_abstract_num_id": self.decimal_abstract_num_id,
            },
            "defaults": dict(self.defaults),
            "styles_by_name": dict(sorted(self.styles_by_name.items(), key=lambda x: x[0].casefold())),
            "styles_by_id": dict(sorted(self.styles_by_id.items(), key=lambda x: x[0])),
            "styles": self.styles_meta
            or [
                {"name": n, "styleId": i, "type": ""}
                for n, i in sorted(self.styles_by_name.items(), key=lambda x: x[0].casefold())
            ],
        }

    def save_json(self, path: Path) -> Path:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.cache_path = path
        return path

    @classmethod
    def from_dict(cls, data: dict, *, docx: Path | None = None) -> "TemplateProfile":
        source = data.get("source") or {}
        root = Path(__file__).resolve().parents[1]
        raw = docx or source.get("docx") or "templates/espd.docx"
        path = Path(raw)
        if not path.is_absolute():
            path = (root / path).resolve()
        styles_by_name = dict(data.get("styles_by_name") or {})
        styles_by_id = dict(data.get("styles_by_id") or {})
        if not styles_by_id and styles_by_name:
            styles_by_id = {sid: name for name, sid in styles_by_name.items()}
        _add_ru_aliases(styles_by_name)
        defaults = dict(PIPELINE_DEFAULTS)
        defaults.update(data.get("defaults") or {})
        numbering = data.get("numbering") or {}
        return cls(
            path=path,
            styles_by_name=styles_by_name,
            styles_by_id=styles_by_id,
            styles_meta=list(data.get("styles") or []),
            defaults=defaults,
            max_num_id=int(numbering.get("max_num_id") or 0),
            bullet_abstract_num_id=str(
                numbering.get("bullet_abstract_num_id") or "0"
            ),
            decimal_abstract_num_id=str(
                numbering.get("decimal_abstract_num_id") or "1"
            ),
            source_sha256=str(source.get("sha256") or ""),
        )

    @classmethod
    def from_json(cls, path: Path, *, docx: Path | None = None) -> "TemplateProfile":
        path = path.resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = cls.from_dict(data, docx=docx)
        profile.cache_path = path
        return profile

    @classmethod
    def from_docx(cls, path: Path) -> "TemplateProfile":
        path = path.resolve()
        with zipfile.ZipFile(path, "r") as z:
            parts = {n: z.read(n) for n in z.namelist()}

        styles_by_name: dict[str, str] = {}
        styles_by_id: dict[str, str] = {}
        styles_meta: list[dict[str, str]] = []
        styles_xml = parts.get("word/styles.xml")
        if styles_xml:
            root = ET.fromstring(styles_xml)
            for st in root.findall(f"{W}style"):
                sid = st.get(f"{W}styleId")
                name_el = st.find(f"{W}name")
                typ = st.get(f"{W}type") or ""
                if sid is None or name_el is None:
                    continue
                name = name_el.get(f"{W}val") or ""
                if not name:
                    continue
                styles_by_id[sid] = name
                styles_by_name.setdefault(name, sid)
                styles_meta.append({"name": name, "styleId": sid, "type": typ})

        _add_ru_aliases(styles_by_name)

        numbering_xml = parts.get("word/numbering.xml", b"")
        max_num_id = 0
        bullet_abs = "0"
        decimal_abs = "1"
        if numbering_xml:
            nroot = ET.fromstring(numbering_xml)
            abs_fmt: dict[str, str] = {}
            for an in nroot.findall(f"{W}abstractNum"):
                aid = an.get(f"{W}abstractNumId")
                if aid is None:
                    continue
                lvl0 = an.find(f"{W}lvl")
                fmt_el = lvl0.find(f"{W}numFmt") if lvl0 is not None else None
                fmt = fmt_el.get(f"{W}val") if fmt_el is not None else ""
                abs_fmt[aid] = fmt or ""
                if fmt == "bullet" and aid == "0":
                    bullet_abs = aid
                if fmt == "decimal" and aid == "1":
                    decimal_abs = aid
            if "0" not in abs_fmt:
                for aid, fmt in abs_fmt.items():
                    if fmt == "bullet":
                        bullet_abs = aid
                        break
            if "1" not in abs_fmt:
                for aid, fmt in abs_fmt.items():
                    if fmt == "decimal":
                        decimal_abs = aid
                        break
            for num in nroot.findall(f"{W}num"):
                nid = num.get(f"{W}numId")
                if nid and nid.isdigit():
                    max_num_id = max(max_num_id, int(nid))

        return cls(
            path=path,
            styles_by_name=styles_by_name,
            styles_by_id=styles_by_id,
            styles_meta=styles_meta,
            defaults=dict(PIPELINE_DEFAULTS),
            numbering_xml=numbering_xml,
            max_num_id=max_num_id,
            bullet_abstract_num_id=bullet_abs,
            decimal_abstract_num_id=decimal_abs,
            source_sha256=_file_sha256(path),
            parts=parts,
        )

    @classmethod
    def load(
        cls,
        docx: Path,
        *,
        cache: Path | None = None,
        refresh: bool = False,
    ) -> "TemplateProfile":
        """Load profile from JSON cache if present and fresh; else parse DOCX.

        If ``cache`` is missing, writes it next to the template as ``*.styles.json``.
        """
        docx = docx.resolve()
        if cache is None:
            cache = docx.with_suffix(docx.suffix + ".styles.json")
            # templates/espd.docx → templates/espd.docx.styles.json is ugly;
            # prefer templates/espd.styles.json
            alt = docx.with_name(docx.stem + ".styles.json")
            cache = alt

        if cache.is_file() and not refresh:
            profile = cls.from_json(cache, docx=docx)
            # Optional integrity: if sha recorded and template changed, re-extract
            if profile.source_sha256 and docx.is_file():
                current = _file_sha256(docx)
                if current != profile.source_sha256:
                    profile = cls.from_docx(docx)
                    profile.save_json(cache)
                    return profile
            return profile

        profile = cls.from_docx(docx)
        profile.save_json(cache)
        return profile


def default_cache_path(docx: Path) -> Path:
    docx = docx.resolve()
    return docx.with_name(docx.stem + ".styles.json")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    ex = sub.add_parser("extract", help="Parse DOCX once and write styles JSON")
    ex.add_argument("docx", type=Path, help="Template DOCX")
    ex.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output JSON (default: <stem>.styles.json next to docx)",
    )

    sh = sub.add_parser("show", help="Show pipeline defaults from cache or DOCX")
    sh.add_argument("docx", type=Path, nargs="?", default=None)
    sh.add_argument("--cache", type=Path, default=None)

    args = ap.parse_args()
    if args.cmd == "extract":
        out = args.output or default_cache_path(args.docx)
        profile = TemplateProfile.from_docx(args.docx)
        profile.save_json(out)
        print(f"Wrote {out} ({len(profile.styles_by_name)} style names)")
        return 0

    # default / show
    root = Path(__file__).resolve().parents[1]
    docx = getattr(args, "docx", None) or root / "templates" / "espd.docx"
    cache = getattr(args, "cache", None)
    if args.cmd == "show" or args.cmd is None:
        if cache is None and docx.with_name(docx.stem + ".styles.json").is_file():
            cache = default_cache_path(docx)
        if cache and Path(cache).is_file():
            profile = TemplateProfile.from_json(Path(cache), docx=docx)
            src = f"cache:{cache}"
        else:
            profile = TemplateProfile.from_docx(docx)
            src = f"docx:{docx}"
        resolved = {
            k: {"name": v, "styleId": profile.style_id(v) if profile.has_style(v) else None}
            for k, v in profile.defaults.items()
        }
        print(
            json.dumps(
                {
                    "source": src,
                    "defaults": resolved,
                    "style_count": len(profile.styles_by_name),
                    "max_num_id": profile.max_num_id,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
