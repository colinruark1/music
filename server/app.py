"""Temporary local backend for the site.

Serves the design source files in design/project/ as real pages, stores
newsletter sign-ups, and runs the admin app at /login and /admin.
Standard library only.

    python3 server/app.py                      # http://127.0.0.1:8000
    PORT=5000 python3 server/app.py
    python3 server/app.py add-admin megan      # create an admin, or reset a password
    python3 server/app.py remove-admin megan
    python3 server/app.py list-admins
"""

import csv
import getpass
import html
import io
import json
import mimetypes
import os
import re
import secrets
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import auth
import mailer
import music
import subscribers
from pages import ASSETS_DIR, render_page
from store import MEDIA_DIR

SERVER_DIR = Path(__file__).resolve().parent
STATIC_DIR = SERVER_DIR / "static"
TEMPLATES_DIR = SERVER_DIR / "templates"

# URL path -> design source file
PAGES = {
    "/": "Main.dc.html",
    "/music": "Music.dc.html",
    "/tour": "Tour.dc.html",
    "/about": "About.dc.html",
    "/subscribe": "Subscribe.dc.html",
    "/player": "Player.dc.html",
}
# How many catalog tracks each page's Music grid shows (None = all).
MUSIC_GRIDS = {"/": 4, "/music": None}

MAX_BODY_BYTES = 10_000
MAX_ADMIN_BODY_BYTES = 200_000
UPLOAD_TYPES = {
    ".jpg": 10_000_000, ".jpeg": 10_000_000, ".png": 10_000_000, ".webp": 10_000_000,
    ".mp3": 60_000_000, ".m4a": 60_000_000, ".wav": 60_000_000,
}
SESSION_COOKIE = "mf_admin"
SECURE_COOKIE = os.environ.get("COOKIE_SECURE") == "1"
ADMIN_CSP = (
    "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' https: data:; "
    "media-src 'self' https:; frame-ancestors 'none'; form-action 'self'"
)


class Handler(BaseHTTPRequestHandler):
    server_version = "MusicSiteDev/0.2"

    # ---------- routing ----------

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        if path in PAGES:
            try:
                page = render_page(PAGES[path])
                if path in MUSIC_GRIDS:
                    page = music.apply_catalog(page, MUSIC_GRIDS[path])
            except (OSError, ValueError) as error:
                return self.send_text(500, f"Could not render {PAGES[path]}: {error}")
            return self.send_body(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if path.startswith("/assets/"):
            return self.send_file(ASSETS_DIR, path[len("/assets/"):])
        if path.startswith("/static/"):
            return self.send_file(STATIC_DIR, path[len("/static/"):])
        if path.startswith("/media/"):
            return self.send_file(MEDIA_DIR, path[len("/media/"):])
        if path == "/api/health":
            return self.send_json(200, {"ok": True})
        if path == "/login":
            if self.admin_user():
                return self.redirect("/admin")
            return self.send_template("login.html")
        if path == "/admin":
            if not self.admin_user():
                return self.redirect("/login")
            return self.send_template("admin.html")
        if path == "/unsubscribe":
            return self.unsubscribe_page(parse_qs(url.query))
        if path.startswith("/api/admin/"):
            user = self.admin_user()
            if not user:
                return self.send_json(401, {"ok": False, "error": "Please log in again."})
            return self.admin_get(path, user)
        self.send_text(404, "Not found")

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/subscribe":
            return self.subscribe()
        if path == "/unsubscribe":
            return self.unsubscribe_post()
        if path == "/api/login":
            return self.login()
        if path == "/api/logout":
            if not self.same_origin():
                return self.send_json(403, {"ok": False, "error": "Cross-site request refused."})
            auth.end_session(self.session_token())
            return self.send_json(200, {"ok": True}, cookie=self.session_cookie("", 0))
        return self.admin_write("POST")

    def do_PUT(self):
        self.admin_write("PUT")

    def do_DELETE(self):
        self.admin_write("DELETE")

    # ---------- public endpoints ----------

    def subscribe(self):
        payload = self.read_json(MAX_BODY_BYTES)
        if payload is None:
            return
        email = payload.get("email", "")
        email = email.strip() if isinstance(email, str) else ""
        if not subscribers.valid_email(email):
            return self.send_json(400, {"ok": False, "error": "That doesn't look like an email address."})
        if subscribers.add(email):
            return self.send_json(201, {"ok": True, "message": "You're on the list."})
        self.send_json(200, {"ok": True, "message": "You're already on the list."})

    def unsubscribe_page(self, query):
        email = query.get("email", [""])[0]
        token = query.get("token", [""])[0]
        if not mailer.check_unsubscribe_token(email, token):
            return self.send_template("unsubscribe.html", {
                "heading": "That link doesn't work",
                "message": "Copy the whole unsubscribe link from the email and try again.",
                "form": "",
            }, status=400)
        form = (
            '<form method="post" action="/unsubscribe">'
            f'<input type="hidden" name="email" value="{_attr(email)}">'
            f'<input type="hidden" name="token" value="{_attr(token)}">'
            '<button type="submit">Unsubscribe</button></form>'
        )
        self.send_template("unsubscribe.html", {
            "heading": "Unsubscribe?",
            "message": f"Stop sending letters to {_attr(email)}.",
            "form": form,
        })

    def unsubscribe_post(self):
        # Both the page's form and mail apps' one-click unsubscribe land here.
        query = parse_qs(urlsplit(self.path).query)
        body = self.read_body(MAX_BODY_BYTES)
        if body is None:
            return
        form = parse_qs(body.decode("utf-8", "replace"))
        email = (form.get("email") or query.get("email") or [""])[0]
        token = (form.get("token") or query.get("token") or [""])[0]
        if not mailer.check_unsubscribe_token(email, token):
            return self.send_template("unsubscribe.html", {
                "heading": "That link doesn't work",
                "message": "Copy the whole unsubscribe link from the email and try again.",
                "form": "",
            }, status=400)
        subscribers.remove(email)
        self.send_template("unsubscribe.html", {
            "heading": "You're unsubscribed",
            "message": f"{_attr(email)} won't get any more letters.",
            "form": '<p><a href="/">Back to the site</a></p>',
        })

    def login(self):
        if not self.same_origin():
            return self.send_json(403, {"ok": False, "error": "Cross-site request refused."})
        client = self.client_address[0]
        if auth.locked_out(client):
            return self.send_json(429, {"ok": False, "error": "Too many attempts. Try again in 15 minutes."})
        payload = self.read_json(MAX_BODY_BYTES)
        if payload is None:
            return
        username = payload.get("username", "")
        password = payload.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
            return self.send_json(400, {"ok": False, "error": "Enter your username and password."})
        if not auth.has_admins():
            return self.send_json(503, {
                "ok": False,
                "error": "No admin accounts yet. Run: python3 server/app.py add-admin <name>",
            })
        user = auth.check_password(username.strip(), password)
        if not user:
            auth.record_failure(client)
            return self.send_json(401, {"ok": False, "error": "Wrong username or password."})
        auth.clear_failures(client)
        token = auth.create_session(user)
        self.send_json(200, {"ok": True}, cookie=self.session_cookie(token, auth.SESSION_SECONDS))

    # ---------- admin API ----------

    def admin_get(self, path, user):
        if path == "/api/admin/session":
            return self.send_json(200, {"ok": True, "username": user, "mail": mailer.status()})
        if path == "/api/admin/subscribers":
            return self.send_json(200, {"ok": True, "subscribers": subscribers.load()})
        if path == "/api/admin/subscribers.csv":
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["email", "subscribed_at"])
            for s in subscribers.load():
                writer.writerow([s["email"], s["subscribed_at"]])
            return self.send_body(200, out.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
                                  extra={"Content-Disposition": 'attachment; filename="subscribers.csv"'})
        if path == "/api/admin/tracks":
            return self.send_json(200, {"ok": True, "tracks": music.load()})
        if path == "/api/admin/campaigns":
            return self.send_json(200, {"ok": True, "campaigns": mailer.campaigns()})
        self.send_json(404, {"ok": False, "error": "Not found"})

    def admin_write(self, method):
        path = urlsplit(self.path).path
        if not path.startswith("/api/admin/"):
            return self.send_text(404, "Not found")
        if not self.same_origin():
            return self.send_json(403, {"ok": False, "error": "Cross-site request refused."})
        user = self.admin_user()
        if not user:
            return self.send_json(401, {"ok": False, "error": "Please log in again."})

        if method == "POST" and path == "/api/admin/uploads":
            return self.upload()

        payload = self.read_json(MAX_ADMIN_BODY_BYTES)
        if payload is None:
            return

        track_match = re.fullmatch(r"/api/admin/tracks/([\w-]+)(/move)?", path)
        if method == "POST" and path == "/api/admin/tracks":
            fields, error = music.clean(payload)
            if error:
                return self.send_json(400, {"ok": False, "error": error})
            return self.send_json(201, {"ok": True, "track": music.add(fields)})
        if track_match and track_match.group(2) and method == "POST":
            offset = -1 if payload.get("direction") == "up" else 1
            if not music.move(track_match.group(1), offset):
                return self.send_json(404, {"ok": False, "error": "That track is gone."})
            return self.send_json(200, {"ok": True})
        if track_match and method == "PUT":
            fields, error = music.clean(payload)
            if error:
                return self.send_json(400, {"ok": False, "error": error})
            track = music.update(track_match.group(1), fields)
            if not track:
                return self.send_json(404, {"ok": False, "error": "That track is gone."})
            return self.send_json(200, {"ok": True, "track": track})
        if track_match and method == "DELETE":
            if not music.delete(track_match.group(1)):
                return self.send_json(404, {"ok": False, "error": "That track is gone."})
            return self.send_json(200, {"ok": True})

        if method == "DELETE" and path == "/api/admin/subscribers":
            email = payload.get("email", "")
            if not isinstance(email, str) or not subscribers.remove(email):
                return self.send_json(404, {"ok": False, "error": "That email isn't on the list."})
            return self.send_json(200, {"ok": True})

        if method == "POST" and path in ("/api/admin/campaigns", "/api/admin/campaigns/test"):
            return self.campaign(payload, user, test=path.endswith("/test"))

        self.send_json(404, {"ok": False, "error": "Not found"})

    def campaign(self, payload, user, test):
        subject = payload.get("subject", "")
        body = payload.get("body", "")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 200 or "\n" in subject:
            return self.send_json(400, {"ok": False, "error": "Write a one-line subject."})
        if not isinstance(body, str) or not body.strip():
            return self.send_json(400, {"ok": False, "error": "Write the message first."})
        track = None
        if payload.get("track_id"):
            track = music.find(str(payload["track_id"]))
            if not track:
                return self.send_json(400, {"ok": False, "error": "That track is no longer in the catalog."})

        if test:
            to = payload.get("to", "")
            to = to.strip() if isinstance(to, str) else ""
            if not subscribers.valid_email(to):
                return self.send_json(400, {"ok": False, "error": "Enter an address to send the test to."})
            try:
                mailer.send_test(to, subject.strip(), body, track)
            except (OSError, mailer.smtplib.SMTPException) as error:
                return self.send_json(502, {"ok": False, "error": f"The mail server refused it: {error}"})
            where = "sent" if mailer.status()["mode"] == "smtp" else "saved to the outbox"
            return self.send_json(200, {"ok": True, "message": f"Test {where} for {to}."})

        record, error = mailer.start_campaign(subject.strip(), body, track, user)
        if error:
            return self.send_json(400, {"ok": False, "error": error})
        self.send_json(202, {"ok": True, "campaign": record})

    def upload(self):
        name = parse_qs(urlsplit(self.path).query).get("name", [""])[0]
        ext = Path(name).suffix.lower()
        if ext not in UPLOAD_TYPES:
            return self.send_json(400, {"ok": False, "error": "Upload a JPG, PNG or WebP image, or an MP3, M4A or WAV file."})
        length = self.content_length()
        if length is None or length == 0 or length > UPLOAD_TYPES[ext]:
            limit = UPLOAD_TYPES[ext] // 1_000_000
            return self.send_json(400, {"ok": False, "error": f"Files of this type can be up to {limit} MB."})
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        target = MEDIA_DIR / f"{secrets.token_hex(8)}{'.jpg' if ext == '.jpeg' else ext}"
        remaining = length
        with target.open("wb") as out:
            while remaining:
                chunk = self.rfile.read(min(remaining, 1 << 16))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining:
            target.unlink(missing_ok=True)
            return self.send_json(400, {"ok": False, "error": "The upload was cut off. Try again."})
        self.send_json(201, {"ok": True, "url": f"/media/{target.name}"})

    # ---------- helpers ----------

    def session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else None

    def admin_user(self):
        return auth.session_user(self.session_token())

    def session_cookie(self, token, max_age):
        flags = "; Secure" if SECURE_COOKIE else ""
        return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{flags}"

    def same_origin(self):
        """Browsers send Origin on every POST/PUT/DELETE; it must be this site."""
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        return bool(host) and origin in (f"http://{host}", f"https://{host}")

    def content_length(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        return length if length >= 0 else None

    def read_body(self, limit):
        length = self.content_length()
        if length is None or length > limit:
            self.send_json(400, {"ok": False, "error": "Request is too large."})
            return None
        return self.rfile.read(length)

    def read_json(self, limit):
        body = self.read_body(limit)
        if body is None:
            return None
        try:
            payload = json.loads(body or b"{}")
        except (ValueError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self.send_json(400, {"ok": False, "error": "Send the request as a JSON object."})
            return None
        return payload

    def send_template(self, name, values=None, status=200):
        page = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        for key, value in (values or {}).items():
            page = page.replace("{{" + key + "}}", value)
        self.send_body(status, page.encode("utf-8"), "text/html; charset=utf-8",
                       extra={"Content-Security-Policy": ADMIN_CSP, "X-Frame-Options": "DENY",
                              "X-Robots-Tag": "noindex, nofollow"})

    def redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def send_file(self, base_dir, name):
        target = (base_dir / name).resolve()
        if base_dir.resolve() not in target.parents or not target.is_file():
            return self.send_text(404, "Not found")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_body(200, target.read_bytes(), content_type)

    def send_json(self, status, payload, cookie=None):
        extra = {"Set-Cookie": cookie} if cookie is not None else None
        self.send_body(status, json.dumps(payload).encode("utf-8"), "application/json", extra=extra)

    def send_text(self, status, text):
        self.send_body(status, text.encode("utf-8"), "text/plain; charset=utf-8")

    def send_body(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Design files are re-read on every request, so never serve a stale copy.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def _attr(value):
    return html.escape(value, quote=True)


def manage_admins(command, args):
    if command == "list-admins":
        names = auth.usernames()
        print("\n".join(names) if names else "No admin accounts yet.")
        return 0
    if len(args) != 1 or not re.fullmatch(r"[\w.@-]{2,64}", args[0]):
        print(f"Usage: python3 server/app.py {command} <username>")
        return 2
    username = args[0]
    if command == "remove-admin":
        if auth.remove_admin(username):
            print(f"Removed {username}.")
            return 0
        print(f"There is no admin called {username}.")
        return 1
    password = getpass.getpass(f"Password for {username}: ")
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        print(f"Use at least {auth.MIN_PASSWORD_LENGTH} characters.")
        return 1
    if getpass.getpass("Type it again: ") != password:
        print("The passwords didn't match.")
        return 1
    auth.set_admin(username, password)
    print(f"Saved {username}. Log in at /login.")
    return 0


def main():
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command in ("add-admin", "remove-admin", "list-admins"):
            sys.exit(manage_admins(command, sys.argv[2:]))
        print(__doc__)
        sys.exit(2)

    mailer.mark_interrupted()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving the site at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    if not auth.has_admins():
        print("No admin accounts yet. Create one with: python3 server/app.py add-admin <name>")
    print(f"Newsletter mail: {mailer.status()['mode']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
