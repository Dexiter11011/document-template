"""GOST-ON–compatible Jinja2 environment: custom filters + undefined handling."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError, UndefinedError
from jinja2.ext import loopcontrols
from jinja2.runtime import Undefined
from jinja2.utils import Namespace


class KeepTokenUndefined(Undefined):
    """Leave unresolved names as ``{{ name }}``; track paths for UI."""

    unresolved: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        name = getattr(self, "_undefined_name", None)
        if name and isinstance(KeepTokenUndefined.unresolved, list):
            if name not in KeepTokenUndefined.unresolved:
                KeepTokenUndefined.unresolved.append(str(name))

    def __str__(self) -> str:
        name = self._undefined_name
        if name:
            return "{{" + str(name) + "}}"
        return ""

    def __iter__(self):
        return iter(())

    def __bool__(self) -> bool:
        return False


class AttrDict(dict):
    """Dict with attribute access for object fields (``obj.name``)."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as e:
            raise AttributeError(item) from e

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


class GostTable:
    """Table variable that stringifies to a GFM markdown table."""

    def __init__(self, headers: list[str] | None = None, rows: list[list[str]] | None = None):
        self.headers = list(headers or [])
        self.rows = [list(r) for r in (rows or [])]

    def __str__(self) -> str:
        return render_table(self.headers, self.rows)

    def __bool__(self) -> bool:
        return bool(self.headers or self.rows)


class GostImage:
    """Image variable: path + alt; filters ``image`` / ``inline``."""

    def __init__(self, path: str = "", alt: str = ""):
        self.path = path or ""
        self.alt = alt or ""

    def __str__(self) -> str:
        return self.path

    def __bool__(self) -> bool:
        return bool(self.path)


def render_list_md(items: list[Any], *, numbered: bool = False) -> str:
    lines: list[str] = []
    for i, item in enumerate(items or [], start=1):
        if isinstance(item, (list, tuple)):
            text = str(item[0]) if item else ""
            prefix = f"{i}." if numbered else "-"
            lines.append(f"{prefix} {text}")
            for j, child in enumerate(item[1:], start=1):
                if numbered:
                    lines.append(f"{i}.{j}. {child}")
                else:
                    lines.append(f"  - {child}")
        else:
            prefix = f"{i}." if numbered else "-"
            lines.append(f"{prefix} {item}")
    return "\n".join(lines)


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not headers and not rows:
        return ""
    cols = len(headers) if headers else (max((len(r) for r in rows), default=0))
    if cols == 0:
        return ""
    hdr = headers if headers else [""] * cols
    hdr = (hdr + [""] * cols)[:cols]
    lines = [
        "| " + " | ".join(str(c) for c in hdr) + " |",
        "| " + " | ".join("---" for _ in range(cols)) + " |",
    ]
    for row in rows:
        cells = (list(row) + [""] * cols)[:cols]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)


def _as_list(value: Any) -> list[Any]:
    if value is None or isinstance(value, Undefined):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def filter_as_bullet_list(value: Any) -> str:
    return render_list_md(_as_list(value), numbered=False)


def filter_as_numbered_list(value: Any) -> str:
    return render_list_md(_as_list(value), numbered=True)


def filter_punctuate_list(value: Any) -> str:
    """Markdown list or list → items joined with ';' and trailing '.'."""
    if isinstance(value, (list, tuple)):
        items = [str(i) for i in value if str(i).strip()]
    else:
        items = []
        for line in str(value).splitlines():
            m = re.match(r"^\s*(?:\d+\.|[-*])\s+(.*)$", line)
            items.append(m.group(1) if m else line.strip())
        items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0] + "."
    return "; ".join(items[:-1]) + "; " + items[-1] + "."


def filter_upper_first(value: Any) -> str:
    s = str(value)
    return s[:1].upper() + s[1:] if s else s


def filter_lower_first(value: Any) -> str:
    s = str(value)
    return s[:1].lower() + s[1:] if s else s


def filter_trim(value: Any) -> str:
    return str(value).strip()


def filter_gost_truncate(value: Any, length: int = 255) -> str:
    """GOST truncate(x): hard cut to length characters (no ellipsis)."""
    s = str(value)
    return s[: int(length)]


def filter_nl2br(value: Any) -> str:
    return str(value).replace("\n", "<br>")


def filter_image(value: Any, caption: str | None = None) -> str:
    if isinstance(value, GostImage):
        path, alt = value.path, value.alt
    else:
        path, alt = str(value), ""
    if caption is None:
        caption = alt
    return f"![{caption or ''}]({path})"


def filter_inline(value: Any, size: str | None = None) -> str:
    if isinstance(value, GostImage):
        path = value.path
    else:
        path = str(value)
    size = size or "1em"
    if size and size[-1].isdigit():
        size = f"{size}em"
    return (
        f'<img src="{html.escape(path, quote=True)}" class="gost-inline-image" '
        f'style="max-height:{html.escape(size)};width:auto;vertical-align:baseline;'
        f'display:inline-block;margin:0">'
    )


def _case_filter(case: str):
    def _f(value: Any) -> str:
        if value is None or isinstance(value, Undefined):
            return str(value)
        if isinstance(value, dict) and case in value:
            return str(value[case])
        if hasattr(value, case) and not isinstance(value, str):
            try:
                return str(getattr(value, case))
            except Exception:  # noqa: BLE001
                pass
        return str(value)

    return _f


def filter_wordcount(value: Any) -> int:
    text = str(value or "")
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def filter_date(value: Any, fmt: str = "%d.%m.%Y") -> str:
    """Format date-like values; pass-through strings that are already formatted."""
    from datetime import date, datetime

    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime(fmt)
    if isinstance(value, date):
        return value.strftime(fmt)
    s = str(value).strip()
    for parse_fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, parse_fmt).strftime(fmt)
        except ValueError:
            continue
    return s


def create_gost_env() -> Environment:
    env = Environment(
        undefined=KeepTokenUndefined,
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
        extensions=[loopcontrols],
    )
    # GOST-specific (Jinja already has upper/lower/replace/first/last/join/urlencode/…)
    env.filters["upper_first"] = filter_upper_first
    env.filters["lower_first"] = filter_lower_first
    env.filters["trim"] = filter_trim
    env.filters["truncate"] = filter_gost_truncate
    env.filters["nl2br"] = filter_nl2br
    env.filters["as_bullet_list"] = filter_as_bullet_list
    env.filters["as_numbered_list"] = filter_as_numbered_list
    env.filters["punctuate_list"] = filter_punctuate_list
    env.filters["image"] = filter_image
    env.filters["inline"] = filter_inline
    env.filters["wordcount"] = filter_wordcount
    env.filters["date"] = filter_date
    for case in ("ip", "rp", "dp", "vp", "tp", "pp"):
        env.filters[case] = _case_filter(case)

    env.globals["namespace"] = Namespace
    return env


_ENV: Environment | None = None


def get_env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = create_gost_env()
    return _ENV


def render_template(source: str, context: dict[str, Any]) -> tuple[str, list[str]]:
    """Render GOST-ON / Jinja template. Returns (text, unresolved names)."""
    KeepTokenUndefined.unresolved = []
    env = get_env()
    try:
        tmpl = env.from_string(source)
        out = tmpl.render(context)
    except TemplateSyntaxError as e:
        msg = f"<!-- GOST template error (line {e.lineno}): {e.message} -->\n{source}"
        return msg, [f"syntax:{e.message}"]
    except UndefinedError as e:
        return source, [str(e)]
    except Exception as e:  # noqa: BLE001 — preview should not crash build
        return f"<!-- GOST template error: {e} -->\n{source}", [str(e)]

    unresolved = list(KeepTokenUndefined.unresolved)
    KeepTokenUndefined.unresolved = []
    return out, unresolved
