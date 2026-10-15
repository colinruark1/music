"""Vercel entry point: every page and API route runs through server/app.py.

vercel.json rewrites all requests (except /assets/ and /static/, which are
served as plain files) to this function.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app import Handler  # noqa: E402


class handler(Handler):
    pass
