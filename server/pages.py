"""Render the canvas .dc.html design files as standalone HTML pages."""

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = ROOT / "design" / "project"
ASSETS_DIR = ROOT / "design" / "assets"


def render_page(source_name):
    """Turn a canvas .dc.html file into a standalone HTML page.

    The canvas runtime (support.js) normally does this in the browser. Here we
    lift out the markup, fill each {{hole}} with its data-props default, and
    point the canvas-only /_blob/ image URLs at design/assets/.
    """
    source = (PROJECT_DIR / source_name).read_text(encoding="utf-8")

    title = re.search(r"<title>(.*?)</title>", source, re.S)
    lang = re.search(r'<html lang="([^"]*)"', source)
    helmet = re.search(r"<helmet>(.*?)</helmet>", source, re.S)
    body = re.search(r"</helmet>(.*?)</x-dc>", source, re.S)
    if not body:
        raise ValueError(f"{source_name} has no <x-dc> markup to render")

    props = {}
    props_attr = re.search(r"data-props='([^']*)'", source)
    if props_attr:
        declared = json.loads(html.unescape(props_attr.group(1)))
        props = {
            name: spec["default"]
            for name, spec in declared.items()
            if isinstance(spec, dict) and "default" in spec
        }

    def fill_hole(match):
        value = props.get(match.group(1))
        return match.group(0) if value is None else html.escape(str(value))

    blobs = json.loads((ASSETS_DIR / "manifest.json").read_text(encoding="utf-8"))

    def local_asset(match):
        name = blobs.get(match.group(1))
        return f"/assets/{name}" if name else match.group(0)

    def localize(fragment):
        fragment = re.sub(r"\{\{\s*([\w$]+)\s*\}\}", fill_hole, fragment)
        return re.sub(r"/_blob/([0-9a-f]{32})", local_asset, fragment)

    return "\n".join(
        [
            "<!doctype html>",
            f'<html lang="{lang.group(1) if lang else "en"}">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{title.group(1) if title else source_name}</title>",
            localize(helmet.group(1)) if helmet else "",
            "</head>",
            "<body>",
            localize(body.group(1)),
            '<script src="/static/site.js"></script>',
            "</body>",
            "</html>",
        ]
    )
