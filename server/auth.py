"""Admin logins.

Passwords are checked by Supabase Auth, and the account must also be listed
in the `admins` table. A successful login gets a signed session cookie, so
sessions work across serverless instances. Removing someone from `admins`
ends their session on the next request.
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import config
import db

MIN_PASSWORD_LENGTH = 9
SESSION_SECONDS = 12 * 60 * 60
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)


def _secret():
    if not config.SESSION_SECRET:
        raise db.DatabaseError("SESSION_SECRET isn't set.")
    return config.SESSION_SECRET.encode("utf-8")


def _sign(data):
    return hmac.new(_secret(), data, hashlib.sha256).digest()


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------- accounts ----------

def admins():
    return db.select("admins", select="user_id,email", order="email.asc")


def set_admin(email, password):
    """Create the login (or reset its password) and allow it into /admin."""
    email = email.strip().lower()
    user = next((u for u in db.auth_users() if (u.get("email") or "").lower() == email), None)
    if user:
        db.set_auth_password(user["id"], password)
    else:
        user = db.create_auth_user(email, password)
    db.insert("admins", {"user_id": user["id"], "email": email}, on_conflict="user_id", ignore_duplicates=True)


def remove_admin(email):
    """Take the account out of /admin. The Supabase Auth login is kept."""
    return bool(db.delete("admins", email=db.eq(email.strip().lower())))


def check_password(email, password):
    """Return the admin's email if the password matches and they're an admin."""
    user = db.sign_in(email.strip().lower(), password)
    if not user:
        return None
    rows = db.select("admins", select="email", user_id=db.eq(user["id"]))
    return {"id": user["id"], "email": rows[0]["email"]} if rows else None


# ---------- lockout ----------

def client_key(address):
    """A keyed hash of the visitor's IP, so no addresses are stored."""
    return hmac.new(_secret(), f"login:{address}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def locked_out(client):
    since = (datetime.now(timezone.utc) - FAILURE_WINDOW).isoformat()
    recent = db.select(
        "login_failures", select="id", client=db.eq(client), failed_at=f"gte.{since}", limit=MAX_FAILURES
    )
    return len(recent) >= MAX_FAILURES


def record_failure(client):
    db.insert("login_failures", {"client": client})
    # Old rows serve no purpose; clear out anything over a day old.
    db.delete("login_failures", failed_at=f"lt.{(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}")


def clear_failures(client):
    db.delete("login_failures", client=db.eq(client))


# ---------- sessions ----------

def create_session(admin):
    payload = json.dumps(
        {"uid": admin["id"], "email": admin["email"], "exp": int(time.time()) + SESSION_SECONDS},
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{_b64(payload)}.{_b64(_sign(payload))}"


def session_user(token):
    """The signed-in admin's email, or None."""
    if not token or "." not in token or not config.SESSION_SECRET:
        return None
    body, signature = token.split(".", 1)
    try:
        payload = _unb64(body)
        if not hmac.compare_digest(_unb64(signature), _sign(payload)):
            return None
        session = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if session.get("exp", 0) < time.time():
        return None
    # Still an admin? This is what makes remove-admin take effect right away.
    rows = db.select("admins", select="email", user_id=db.eq(session.get("uid", "")))
    return rows[0]["email"] if rows else None
