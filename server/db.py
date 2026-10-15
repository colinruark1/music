"""A small Supabase client over HTTPS, using the standard library only.

Every call uses the secret key, which bypasses row-level security. The tables
have RLS turned on with no policies, so the public key can't touch them.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import config

TIMEOUT_SECONDS = 15


class DatabaseError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _headers(extra=None):
    key = config.SUPABASE_SECRET_KEY
    if not key:
        raise DatabaseError("Supabase isn't connected: set SUPABASE_SECRET_KEY.")
    headers = {"apikey": key, "Content-Type": "application/json"}
    # Legacy service_role keys are JWTs and go in Authorization too; the newer
    # sb_secret_ keys only go in apikey.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    headers.update(extra or {})
    return headers


def call(method, path, params=None, body=None, headers=None):
    """Send a request to the Supabase API; return the decoded JSON (or None)."""
    url = config.SUPABASE_URL + path
    if params:
        url += "?" + urlencode(params, safe=",.()*:")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method=method, headers=_headers(headers))
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("message") or parsed.get("msg") or parsed.get("error_description") or parsed.get("error") or detail
        except ValueError:
            pass
        raise DatabaseError(str(detail), error.code) from None
    except (URLError, TimeoutError, OSError) as error:
        raise DatabaseError(f"Couldn't reach Supabase: {error}") from None
    return json.loads(raw) if raw else None


# ---------- tables (PostgREST) ----------

def select(table, **params):
    return call("GET", f"/rest/v1/{table}", params) or []


def insert(table, rows, on_conflict=None, ignore_duplicates=False):
    prefer = "return=representation"
    if ignore_duplicates:
        prefer += ",resolution=ignore-duplicates"
    params = {"on_conflict": on_conflict} if on_conflict else None
    return call("POST", f"/rest/v1/{table}", params, rows, {"Prefer": prefer}) or []


def update(table, values, **filters):
    return call("PATCH", f"/rest/v1/{table}", filters, values, {"Prefer": "return=representation"}) or []


def delete(table, **filters):
    return call("DELETE", f"/rest/v1/{table}", filters, None, {"Prefer": "return=representation"}) or []


def rpc(function, **args):
    return call("POST", f"/rest/v1/rpc/{function}", body=args)


def eq(value):
    return f"eq.{value}"


# ---------- auth ----------

def sign_in(email, password):
    """Check a password with Supabase Auth. Returns the user, or None if wrong."""
    try:
        session = call("POST", "/auth/v1/token", {"grant_type": "password"}, {"email": email, "password": password})
    except DatabaseError as error:
        if error.status in (400, 401, 422):
            return None
        raise
    return session.get("user") if session else None


def auth_users():
    users, page = [], 1
    while True:
        batch = call("GET", "/auth/v1/admin/users", {"page": page, "per_page": 200}).get("users", [])
        users.extend(batch)
        if len(batch) < 200:
            return users
        page += 1


def create_auth_user(email, password):
    return call("POST", "/auth/v1/admin/users", body={"email": email, "password": password, "email_confirm": True})


def set_auth_password(user_id, password):
    return call("PUT", f"/auth/v1/admin/users/{user_id}", body={"password": password})


# ---------- storage ----------

def public_url(bucket, path):
    return f"{config.SUPABASE_URL}/storage/v1/object/public/{bucket}/{quote(path)}"


def signed_upload_url(bucket, path):
    """A one-time URL the browser can PUT a file to, straight into Storage."""
    data = call("POST", f"/storage/v1/object/upload/sign/{bucket}/{quote(path)}", body={})
    return config.SUPABASE_URL + "/storage/v1" + data["url"]
