"""Admin accounts and login sessions.

Accounts live in server/data/admins.json as salted PBKDF2 hashes and are
managed from the command line (see app.py). Sessions are kept in memory, so
restarting the server signs everyone out.
"""

import hashlib
import hmac
import secrets
import threading
import time

from store import LOCK, read_json, write_json

FILE = "admins.json"
ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10
SESSION_SECONDS = 12 * 60 * 60
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60

_sessions = {}  # token -> (username, expires_at)
_failures = {}  # client address -> [failure times]
_state_lock = threading.Lock()
# Hashed when the username is unknown, so a miss takes as long as a wrong password.
_DUMMY = {"salt": secrets.token_hex(16), "hash": "", "iterations": ITERATIONS}


def _hash(password, salt, iterations):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    ).hex()


def _admins():
    return read_json(FILE, [])


def has_admins():
    return bool(_admins())


def usernames():
    return [a["username"] for a in _admins()]


def set_admin(username, password):
    """Create the account, or reset its password if it exists."""
    salt = secrets.token_hex(16)
    record = {
        "username": username,
        "salt": salt,
        "hash": _hash(password, salt, ITERATIONS),
        "iterations": ITERATIONS,
    }
    with LOCK:
        admins = [a for a in _admins() if a["username"].lower() != username.lower()]
        admins.append(record)
        write_json(FILE, admins)


def remove_admin(username):
    with LOCK:
        admins = _admins()
        kept = [a for a in admins if a["username"].lower() != username.lower()]
        if len(kept) == len(admins):
            return False
        write_json(FILE, kept)
    with _state_lock:
        for token, (user, _) in list(_sessions.items()):
            if user.lower() == username.lower():
                del _sessions[token]
    return True


def check_password(username, password):
    """Return the account's username if the password matches, else None."""
    admin = next(
        (a for a in _admins() if a["username"].lower() == username.lower()), None
    )
    record = admin or _DUMMY
    attempt = _hash(password, record["salt"], record["iterations"])
    if admin and hmac.compare_digest(attempt, admin["hash"]):
        return admin["username"]
    return None


def locked_out(client):
    now = time.time()
    with _state_lock:
        recent = [t for t in _failures.get(client, []) if now - t < FAILURE_WINDOW_SECONDS]
        _failures[client] = recent
        return len(recent) >= MAX_FAILURES


def record_failure(client):
    with _state_lock:
        _failures.setdefault(client, []).append(time.time())


def clear_failures(client):
    with _state_lock:
        _failures.pop(client, None)


def create_session(username):
    token = secrets.token_urlsafe(32)
    with _state_lock:
        _sessions[token] = (username, time.time() + SESSION_SECONDS)
    return token


def session_user(token):
    if not token:
        return None
    with _state_lock:
        entry = _sessions.get(token)
        if not entry:
            return None
        username, expires_at = entry
        if time.time() > expires_at:
            del _sessions[token]
            return None
    # An account removed from the command line loses its sessions too.
    return username if username in usernames() else None


def end_session(token):
    with _state_lock:
        _sessions.pop(token, None)
