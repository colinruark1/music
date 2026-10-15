"""Settings from environment variables, plus a .env loader for local runs.

On Vercel, set these under Project Settings -> Environment Variables. Locally,
put them in .env.local or .env at the repo root (both are gitignored).
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"  # local-only files (the outbox)
SUPABASE_PROJECT = "xrakfsbzwzchnplfjney"


def load_env():
    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            os.environ.setdefault(key, value)


load_env()


def get(name, default=""):
    return os.environ.get(name, default)


ON_VERCEL = bool(get("VERCEL"))
SUPABASE_URL = get("SUPABASE_URL", f"https://{SUPABASE_PROJECT}.supabase.co").rstrip("/")
# The secret (service role) key. Server-side only: never send it to a browser.
SUPABASE_SECRET_KEY = get("SUPABASE_SECRET_KEY") or get("SUPABASE_SERVICE_ROLE_KEY")
# Signs admin session cookies and unsubscribe links. Changing it logs admins
# out and breaks the unsubscribe links in emails already sent.
SESSION_SECRET = get("SESSION_SECRET")
COOKIE_SECURE = ON_VERCEL or get("COOKIE_SECURE") == "1"


def missing():
    """Names of required settings that aren't set."""
    return [
        name
        for name, value in (("SUPABASE_SECRET_KEY", SUPABASE_SECRET_KEY), ("SESSION_SECRET", SESSION_SECRET))
        if not value
    ]
