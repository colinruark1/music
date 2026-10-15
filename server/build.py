"""Render the site to static files in public/, for hosts like Vercel.

    python3 server/build.py

Writes public/index.html, public/music.html, ... plus the assets and
site.js. Vercel serves them with clean URLs (/music -> music.html; see
vercel.json). Only the public pages are built: sign-ups, /login and /admin
need the Python server and don't work on a static host.
"""

import shutil
from pathlib import Path

from app import PAGES, STATIC_DIR
from pages import ASSETS_DIR, ROOT, render_page

OUT_DIR = ROOT / "public"


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir()
    for path, source in PAGES.items():
        name = "index.html" if path == "/" else f"{path.strip('/')}.html"
        (OUT_DIR / name).write_text(render_page(source), encoding="utf-8")
        print(f"{path:<12} -> public/{name}")
    shutil.copytree(ASSETS_DIR, OUT_DIR / "assets", ignore=shutil.ignore_patterns("manifest.json"))
    (OUT_DIR / "static").mkdir()
    shutil.copy2(STATIC_DIR / "site.js", OUT_DIR / "static" / "site.js")


if __name__ == "__main__":
    main()
