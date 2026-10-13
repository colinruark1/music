"""Temporary local backend for the site.

Serves the design source files in design/project/ as real pages and stores
newsletter sign-ups in a JSON file. Standard library only.

    python3 server/app.py            # http://127.0.0.1:8000
    PORT=5000 python3 server/app.py
"""

import html
import json
import mimetypes
import os
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = ROOT / "design" / "project"
ASSETS_DIR = ROOT / "design" / "assets"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(__file__).resolve().parent / "data"
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"

# URL path -> design source file
PAGES = {
    "/": "Main.dc.html",
    "/player": "Player.dc.html",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_BODY_BYTES = 10_000

_subscribers_lock = threading.Lock()


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


def load_subscribers():
    if not SUBSCRIBERS_FILE.exists():
        return []
    return json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))


def add_subscriber(email):
    """Store the email. Returns False if it was already on the list."""
    with _subscribers_lock:
        subscribers = load_subscribers()
        if any(s["email"].lower() == email.lower() for s in subscribers):
            return False
        subscribers.append(
            {"email": email, "subscribed_at": datetime.now(timezone.utc).isoformat()}
        )
        DATA_DIR.mkdir(exist_ok=True)
        tmp = SUBSCRIBERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(subscribers, indent=2) + "\n", encoding="utf-8")
        tmp.replace(SUBSCRIBERS_FILE)
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "MusicSiteDev/0.1"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in PAGES:
            try:
                page = render_page(PAGES[path])
            except (OSError, ValueError) as error:
                return self.send_text(500, f"Could not render {PAGES[path]}: {error}")
            return self.send_body(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if path.startswith("/assets/"):
            return self.send_file(ASSETS_DIR, path[len("/assets/"):])
        if path.startswith("/static/"):
            return self.send_file(STATIC_DIR, path[len("/static/"):])
        if path == "/api/health":
            return self.send_json(200, {"ok": True})
        if path == "/api/subscribers":
            return self.send_json(200, {"subscribers": load_subscribers()})
        self.send_text(404, "Not found")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/subscribe":
            return self.send_text(404, "Not found")

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            return self.send_json(400, {"ok": False, "error": "Request is too large."})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            email = payload.get("email", "") if isinstance(payload, dict) else ""
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {"ok": False, "error": "Send JSON like {\"email\": \"you@example.com\"}."})

        email = email.strip() if isinstance(email, str) else ""
        if len(email) > 254 or not EMAIL_RE.match(email):
            return self.send_json(400, {"ok": False, "error": "That doesn't look like an email address."})

        if add_subscriber(email):
            return self.send_json(201, {"ok": True, "message": "You're on the list."})
        self.send_json(200, {"ok": True, "message": "You're already on the list."})

    def send_file(self, base_dir, name):
        target = (base_dir / name).resolve()
        if base_dir.resolve() not in target.parents or not target.is_file():
            return self.send_text(404, "Not found")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_body(200, target.read_bytes(), content_type)

    def send_json(self, status, payload):
        self.send_body(status, json.dumps(payload).encode("utf-8"), "application/json")

    def send_text(self, status, text):
        self.send_body(status, text.encode("utf-8"), "text/plain; charset=utf-8")

    def send_body(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Design files are re-read on every request, so never serve a stale copy.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving the site at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
