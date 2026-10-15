"""Newsletter sign-ups, stored in the Supabase `subscribers` table."""

import re

import db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize(email):
    return email.strip().lower() if isinstance(email, str) else ""


def valid_email(email):
    return isinstance(email, str) and len(email) <= 254 and bool(EMAIL_RE.match(email))


def load():
    return db.select("subscribers", select="email,subscribed_at", order="subscribed_at.asc")


def add(email):
    """Store the email. Returns False if it was already on the list."""
    rows = db.insert("subscribers", {"email": normalize(email)}, on_conflict="email", ignore_duplicates=True)
    return bool(rows)


def remove(email):
    """Take the email off the list, and out of the records of past sends, as
    the privacy policy promises. Returns False if it wasn't on the list."""
    email = normalize(email)
    removed = bool(db.delete("subscribers", email=db.eq(email)))
    db.delete("deliveries", email=db.eq(email))
    return removed
