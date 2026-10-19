"""Backend for the site: public pages, newsletter sign-ups, and the admin app
at /login and /admin. Data lives in Supabase (see supabase/migrations/).
Standard library only. Runs locally, and on Vercel through api/index.py.

    python3 server/app.py                            # http://127.0.0.1:8000
    PORT=5000 python3 server/app.py
    python3 server/app.py add-admin you@example.com  # create an admin, or reset a password
    python3 server/app.py remove-admin you@example.com
    python3 server/app.py list-admins
"""

import csv
import getpass
import html
import io
import json
import mimetypes
import re
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import config  # first: loads .env before anything reads settings
import auth
import content
import db
import mailer
import music
import subscribers
from pages import ASSETS_DIR, render_page

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
    "/privacy": "Privacy.dc.html",
}
# How many catalog tracks each page's Music grid shows (None = all).
MUSIC_GRIDS = {"/": 4, "/music": None}

MAX_BODY_BYTES = 10_000
MAX_ADMIN_BODY_BYTES = 200_000
SESSION_COOKIE = "mf_admin"
ADMIN_CSP = (
    "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    f"font-src https://fonts.gstatic.com; img-src 'self' https: data: {config.SUPABASE_URL}; "
    f"connect-src 'self' {config.SUPABASE_URL}; media-src 'self' https: {config.SUPABASE_URL}; "
    "frame-ancestors 'none'; form-action 'self'"
)
BAD_UNSUBSCRIBE = {
    "heading": "That link doesn't work",
    "message": "Copy the whole unsubscribe link from the email and try again.",
    "form": "",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "MeganFaithSite/0.3"

    # ---------- routing ----------

    def do_GET(self):
        self.guard(self.route_get)

    def do_POST(self):
        self.guard(self.route_post)

    def do_PUT(self):
        self.guard(lambda: self.admin_write("PUT"))

    def do_DELETE(self):
        self.guard(lambda: self.admin_write("DELETE"))

    def guard(self, route):
        """Turn a Supabase outage into a clear error instead of a crash."""
        try:
            route()
        except db.DatabaseError as error:
            self.log_error("Supabase: %s", error)
            if urlsplit(self.path).path.startswith("/api/"):
                self.send_json(503, {"ok": False, "error": f"The database isn't answering: {error}"})
            else:
                self.send_text(503, "The site's database isn't answering. Try again in a minute.")

    def route_get(self):
        url = urlsplit(self.path)
        path = url.path
        if path in PAGES:
            try:
                page = render_page(PAGES[path])
            except (OSError, ValueError) as error:
                return self.send_text(500, f"Could not render {PAGES[path]}: {error}")
            page = content.apply_content(page)
            if path in MUSIC_GRIDS:
                page = music.apply_catalog(page, MUSIC_GRIDS[path])
            return self.send_body(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if path.startswith("/assets/"):
            return self.send_file(ASSETS_DIR, path[len("/assets/"):])
        if path.startswith("/static/"):
            return self.send_file(STATIC_DIR, path[len("/static/"):])
        if path == "/api/health":
            return self.send_json(200, {"ok": True, "missing_settings": config.missing()})
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

    def route_post(self):
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
            return self.send_json(200, {"ok": True}, cookie=self.session_cookie("", 0))
        return self.admin_write("POST")

    # ---------- public endpoints ----------

    def subscribe(self):
        payload = self.read_json(MAX_BODY_BYTES)
        if payload is None:
            return
        email = subscribers.normalize(payload.get("email", ""))
        if not subscribers.valid_email(email):
            return self.send_json(400, {"ok": False, "error": "That doesn't look like an email address."})
        if subscribers.add(email):
            return self.send_json(201, {"ok": True, "message": "You're on the list."})
        self.send_json(200, {"ok": True, "message": "You're already on the list."})

    def unsubscribe_page(self, query):
        email = query.get("email", [""])[0]
        token = query.get("token", [""])[0]
        if not mailer.check_unsubscribe_token(email, token):
            return self.send_template("unsubscribe.html", BAD_UNSUBSCRIBE, status=400)
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
            return self.send_template("unsubscribe.html", BAD_UNSUBSCRIBE, status=400)
        subscribers.remove(email)
        self.send_template("unsubscribe.html", {
            "heading": "You're unsubscribed",
            "message": f"{_attr(email)} won't get any more letters.",
            "form": '<p><a href="/">Back to the site</a></p>',
        })

    def login(self):
        if not self.same_origin():
            return self.send_json(403, {"ok": False, "error": "Cross-site request refused."})
        if config.missing():
            return self.send_json(503, {
                "ok": False, "error": "The server isn't set up yet: missing " + ", ".join(config.missing()) + ".",
            })
        client = auth.client_key(self.client_ip())
        if auth.locked_out(client):
            return self.send_json(429, {"ok": False, "error": "Too many attempts. Try again in 15 minutes."})
        payload = self.read_json(MAX_BODY_BYTES)
        if payload is None:
            return
        email = payload.get("email", "")
        password = payload.get("password", "")
        if not isinstance(email, str) or not isinstance(password, str) or not email or not password or len(password) > 1024:
            return self.send_json(400, {"ok": False, "error": "Enter your email and password."})
        admin = auth.check_password(email, password)
        if not admin:
            auth.record_failure(client)
            return self.send_json(401, {"ok": False, "error": "Wrong email or password."})
        auth.clear_failures(client)
        token = auth.create_session(admin)
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
        if path == "/api/admin/content":
            return self.send_json(200, {"ok": True, "sections": content.for_admin()})
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

        payload = self.read_json(MAX_ADMIN_BODY_BYTES)
        if payload is None:
            return

        if method == "POST" and path == "/api/admin/uploads":
            size = payload.get("size")
            target, error = music.upload_target(str(payload.get("name", "")), size if isinstance(size, int) else None)
            if error:
                return self.send_json(400, {"ok": False, "error": error})
            return self.send_json(201, {"ok": True, **target})

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

        content_match = re.fullmatch(r"/api/admin/content/(\w+)", path)
        if content_match and method == "PUT":
            value, error = content.clean(content_match.group(1), payload)
            if error:
                return self.send_json(400, {"ok": False, "error": error})
            content.save(content_match.group(1), value, user)
            return self.send_json(200, {"ok": True, "value": value})
        if content_match and method == "DELETE":
            if content_match.group(1) not in content.SECTIONS:
                return self.send_json(404, {"ok": False, "error": "That section doesn't exist."})
            content.reset(content_match.group(1))
            return self.send_json(200, {"ok": True})

        if method == "DELETE" and path == "/api/admin/subscribers":
            email = payload.get("email", "")
            if not isinstance(email, str) or not subscribers.remove(email):
                return self.send_json(404, {"ok": False, "error": "That email isn't on the list."})
            return self.send_json(200, {"ok": True})

        if method == "POST" and path in ("/api/admin/campaigns", "/api/admin/campaigns/test"):
            return self.campaign(payload, user, test=path.endswith("/test"))

        send_match = re.fullmatch(r"/api/admin/campaigns/([\w-]+)/send", path)
        if method == "POST" and send_match:
            summary = mailer.send_batch(send_match.group(1))
            if not summary:
                return self.send_json(404, {"ok": False, "error": "That send is gone."})
            return self.send_json(200, {"ok": True, "campaign": summary})

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
            where = "sent" if mailer.mode() == "smtp" else "saved to the outbox"
            return self.send_json(200, {"ok": True, "message": f"Test {where} for {to}."})

        record, error = mailer.start_campaign(subject.strip(), body, track, user)
        if error:
            return self.send_json(400, {"ok": False, "error": error})
        self.send_json(202, {"ok": True, "campaign": record})

    # ---------- helpers ----------

    def client_ip(self):
        if config.ON_VERCEL:
            # Vercel sets this to the visitor's address; it can't be spoofed there.
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else None

    def admin_user(self):
        return auth.session_user(self.session_token())

    def session_cookie(self, token, max_age):
        flags = "; Secure" if config.COOKIE_SECURE else ""
        return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{flags}"

    def same_origin(self):
        """Browsers send Origin on every POST/PUT/DELETE; it must be this site."""
        origin = self.headers.get("Origin", "")
        host = self.headers.get("X-Forwarded-Host") if config.ON_VERCEL else None
        host = host or self.headers.get("Host", "")
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
        # Pages are rebuilt on every request (design files, catalog), so never cache.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def _attr(value):
    return html.escape(value, quote=True)


def manage_admins(command, args):
    if config.missing():
        print("Set these first (in .env.local or the environment): " + ", ".join(config.missing()))
        return 1
    if command == "list-admins":
        rows = auth.admins()
        print("\n".join(r["email"] for r in rows) if rows else "No admin accounts yet.")
        return 0
    if len(args) != 1 or not subscribers.valid_email(args[0]):
        print(f"Usage: python3 server/app.py {command} <email>")
        return 2
    email = args[0]
    if command == "remove-admin":
        if auth.remove_admin(email):
            print(f"{email} can no longer use /admin.")
            return 0
        print(f"{email} isn't an admin.")
        return 1
    password = getpass.getpass(f"Password for {email}: ")
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        print(f"Use at least {auth.MIN_PASSWORD_LENGTH} characters.")
        return 1
    if getpass.getpass("Type it again: ") != password:
        print("The passwords didn't match.")
        return 1
    auth.set_admin(email, password)
    print(f"Saved {email}. Log in at /login.")
    return 0


def main():
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command in ("add-admin", "remove-admin", "list-admins"):
            try:
                sys.exit(manage_admins(command, sys.argv[2:]))
            except db.DatabaseError as error:
                print(f"Supabase said: {error}")
                sys.exit(1)
        print(__doc__)
        sys.exit(2)

    port = int(config.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving the site at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    if config.missing():
        print("Not connected to Supabase yet. Missing: " + ", ".join(config.missing()) + " (see README).")
    print(f"Newsletter mail: {mailer.mode()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
