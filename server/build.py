"""Copy the site's images and scripts into public/ for Vercel.

    python3 server/build.py

Vercel serves public/ as plain files (/assets/..., /static/...). Pages are
not built here: they come from the Python function in api/index.py, so the
Music grid always shows the current catalog. A page file in public/ would
be served instead of the function, so this script never writes one.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "public"


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    shutil.copytree(ROOT / "design" / "assets", OUT_DIR / "assets", ignore=shutil.ignore_patterns("manifest.json"))
    shutil.copytree(ROOT / "server" / "static", OUT_DIR / "static")
    print("Copied design/assets/ and server/static/ into public/")


if __name__ == "__main__":
    main()
