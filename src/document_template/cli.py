"""CLI for document-template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from document_template.profile import TemplateProfile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="document-template")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract-styles", help="Extract style cache from DOCX catalog")
    extract.add_argument("docx", type=Path)
    extract.add_argument("-o", "--output", type=Path)

    render = sub.add_parser("render", help="Render Jinja markdown template")
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--context", type=Path, required=True)
    render.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    if args.command == "extract-styles":
        profile = TemplateProfile.load(args.docx, refresh=True)
        out = args.output or args.docx.with_name(args.docx.stem + ".styles.json")
        out.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {out}")
        return 0
    if args.command == "render":
        from document_template.jinja_env import render_template

        ctx = json.loads(args.context.read_text(encoding="utf-8"))
        text, _ = render_template(args.input.read_text(encoding="utf-8"), ctx)
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
