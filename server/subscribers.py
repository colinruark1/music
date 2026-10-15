"""Newsletter sign-ups, stored in server/data/subscribers.json."""

import re
from datetime import datetime, timezone

from store import LOCK, read_json, write_json

FILE = "subscribers.json"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email):
    return isinstance(email, str) and len(email) <= 254 and bool(EMAIL_RE.match(email))


def load():
    return read_json(FILE, [])


def add(email):
    """Store the email. Returns False if it was already on the list."""
    with LOCK:
        subscribers = load()
        if any(s["email"].lower() == email.lower() for s in subscribers):
            return False
        subscribers.append(
            {"email": email, "subscribed_at": datetime.now(timezone.utc).isoformat()}
        )
        write_json(FILE, subscribers)
        return True


def remove(email):
    """Take the email off the list. Returns False if it wasn't on it."""
    with LOCK:
        subscribers = load()
        kept = [s for s in subscribers if s["email"].lower() != email.lower()]
        if len(kept) == len(subscribers):
            return False
        write_json(FILE, kept)
        return True
