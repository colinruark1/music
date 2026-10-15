"""Newsletter emails: compose, send through SMTP, and track each send.

Configured with environment variables:

    SMTP_HOST, SMTP_PORT (587), SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_SECURITY (starttls | ssl | none, default starttls),
    MAIL_FROM ("Megan Faith <hello@example.com>"),
    SITE_URL (the public address of the site, used for links and images).

Without SMTP_HOST, nothing is sent: each email is written to
server/data/outbox/<send id>/ as an .eml file you can open in a mail app.
"""

import hashlib
import hmac
import html
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from urllib.parse import urlencode

import subscribers
from store import DATA_DIR, LOCK, read_json, write_json

CAMPAIGNS_FILE = "campaigns.json"
SECRET_FILE = DATA_DIR / "secret.key"
OUTBOX_DIR = DATA_DIR / "outbox"
ARTIST = "Megan Faith"
SEND_DELAY_SECONDS = 0.2  # stay well under typical SMTP rate limits

# Long unsubscribe URLs must stay on one header line, not get MIME-encoded.
_POLICY = policy.SMTP.clone(max_line_length=998)
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def settings():
    port = os.environ.get("PORT", "8000")
    return {
        "host": os.environ.get("SMTP_HOST", ""),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "username": os.environ.get("SMTP_USERNAME", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "security": os.environ.get("SMTP_SECURITY", "starttls").lower(),
        "from": os.environ.get("MAIL_FROM", f"{ARTIST} <newsletter@localhost>"),
        "site_url": os.environ.get("SITE_URL", f"http://127.0.0.1:{port}").rstrip("/"),
    }


def status():
    config = settings()
    return {
        "mode": "smtp" if config["host"] else "outbox",
        "from": config["from"],
        "site_url": config["site_url"],
        "outbox": str(OUTBOX_DIR),
    }


def _secret():
    with LOCK:
        if not SECRET_FILE.exists():
            DATA_DIR.mkdir(exist_ok=True)
            SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
            SECRET_FILE.chmod(0o600)
        return bytes.fromhex(SECRET_FILE.read_text(encoding="utf-8").strip())


def unsubscribe_token(email):
    return hmac.new(_secret(), email.lower().encode("utf-8"), hashlib.sha256).hexdigest()


def check_unsubscribe_token(email, token):
    return hmac.compare_digest(unsubscribe_token(email), token or "")


def unsubscribe_url(email):
    query = urlencode({"email": email, "token": unsubscribe_token(email)})
    return f"{settings()['site_url']}/unsubscribe?{query}"


def _absolute(url, site_url):
    return url if url.startswith("http") else site_url + url


def _body_html(text):
    paragraphs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        escaped = html.escape(block)
        linked = _URL_RE.sub(
            lambda m: f'<a href="{m.group(0)}" style="color:#1B242A">{m.group(0)}</a>', escaped
        )
        paragraphs.append(
            f'<p style="margin:0 0 16px;font-size:16px;line-height:1.6">{linked.replace(chr(10), "<br>")}</p>'
        )
    return "".join(paragraphs)


def build_message(to, subject, body, track=None):
    config = settings()
    site = config["site_url"]
    unsubscribe = unsubscribe_url(to)

    text = body.strip() + "\n"
    track_html = ""
    if track:
        link = _absolute(track["link"], site)
        text += f"\n{track['title']}\n{track['link_label']}: {link}\n"
        track_html = (
            '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 24px">'
            f'<tr><td><a href="{html.escape(link)}"><img src="{html.escape(_absolute(track["cover"], site))}" '
            f'alt="{html.escape(track["cover_alt"])}" width="240" height="240" '
            'style="display:block;width:240px;height:240px;object-fit:cover;border:6px solid #FAFAF7"></a></td></tr>'
            '<tr><td style="padding-top:12px;font-family:Georgia,serif;font-size:24px;color:#1B242A">'
            f'{html.escape(track["title"])}</td></tr>'
            f'<tr><td style="padding-top:6px"><a href="{html.escape(link)}" style="color:#1B242A;'
            'font-family:\'Arial Narrow\',Arial,sans-serif;font-weight:bold;letter-spacing:.12em;'
            f'text-transform:uppercase;font-size:14px">{html.escape(track["link_label"])}</a></td></tr></table>'
        )
    text += f"\n--\nYou're getting this because you signed up at {site}.\nUnsubscribe: {unsubscribe}\n"

    message = EmailMessage(policy=_POLICY)
    message["Subject"] = subject
    message["From"] = config["from"]
    message["To"] = to
    message["Date"] = formatdate(localtime=True)
    domain = parseaddr(config["from"])[1].rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=domain)
    message["List-Unsubscribe"] = f"<{unsubscribe}>"
    message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(text)
    message.add_alternative(
        '<!doctype html><html><body style="margin:0;background:#F1EEE6;color:#1B242A;'
        'font-family:Helvetica,Arial,sans-serif">'
        '<div style="max-width:560px;margin:0 auto;padding:32px 24px">'
        f'<div style="font-family:\'Arial Narrow\',Arial,sans-serif;font-weight:bold;font-size:20px;'
        f'letter-spacing:.16em;text-transform:uppercase;margin-bottom:28px">{html.escape(ARTIST)}</div>'
        f"{_body_html(body)}{track_html}"
        '<p style="margin:32px 0 0;padding-top:16px;border-top:1px solid #C3C9CA;font-size:13px;color:#546067">'
        f'You\'re getting this because you signed up at <a href="{html.escape(site)}" style="color:#546067">'
        f'{html.escape(site)}</a>. <a href="{html.escape(unsubscribe)}" style="color:#546067">Unsubscribe</a>.</p>'
        "</div></body></html>",
        subtype="html",
    )
    return message


class _Sender:
    """One SMTP connection reused across a send, or an outbox folder."""

    def __init__(self, outbox_name):
        self.config = settings()
        self.outbox = OUTBOX_DIR / outbox_name
        self.smtp = None

    def _connect(self):
        c = self.config
        if c["security"] == "ssl":
            smtp = smtplib.SMTP_SSL(c["host"], c["port"], timeout=30, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(c["host"], c["port"], timeout=30)
            if c["security"] == "starttls":
                smtp.starttls(context=ssl.create_default_context())
        if c["username"]:
            smtp.login(c["username"], c["password"])
        return smtp

    def send(self, message):
        if not self.config["host"]:
            self.outbox.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^\w.@-]", "_", message["To"]) + ".eml"
            (self.outbox / name).write_bytes(bytes(message))
            return
        try:
            self.smtp = self.smtp or self._connect()
            self.smtp.send_message(message)
        except smtplib.SMTPServerDisconnected:
            self.smtp = self._connect()
            self.smtp.send_message(message)

    def close(self):
        if self.smtp:
            try:
                self.smtp.quit()
            except smtplib.SMTPException:
                pass


def send_test(to, subject, body, track=None):
    sender = _Sender("tests")
    try:
        sender.send(build_message(to, f"[Test] {subject}", body, track))
    finally:
        sender.close()


def campaigns():
    return read_json(CAMPAIGNS_FILE, [])


def _update_campaign(campaign_id, **changes):
    with LOCK:
        records = campaigns()
        for record in records:
            if record["id"] == campaign_id:
                record.update(changes)
        write_json(CAMPAIGNS_FILE, records)


def mark_interrupted():
    """Sends that were running when the server last stopped didn't finish."""
    with LOCK:
        records = campaigns()
        if any(r["status"] == "sending" for r in records):
            for record in records:
                if record["status"] == "sending":
                    record["status"] = "interrupted"
            write_json(CAMPAIGNS_FILE, records)


def start_campaign(subject, body, track, sent_by):
    """Queue a send to every subscriber. Returns (record, error)."""
    recipients = [s["email"] for s in subscribers.load()]
    if not recipients:
        return None, "Nobody has signed up yet."
    with LOCK:
        records = campaigns()
        if any(r["status"] == "sending" for r in records):
            return None, "Another email is still sending. Wait for it to finish."
        record = {
            "id": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3),
            "subject": subject,
            "body": body,
            "track_id": track["id"] if track else None,
            "track_title": track["title"] if track else None,
            "sent_by": sent_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": status()["mode"],
            "status": "sending",
            "recipients": len(recipients),
            "sent": 0,
            "failed": 0,
            "errors": [],
        }
        records.insert(0, record)
        write_json(CAMPAIGNS_FILE, records)

    threading.Thread(
        target=_run_campaign, args=(record, recipients, track), daemon=True
    ).start()
    return record, None


def _run_campaign(record, recipients, track):
    sender = _Sender(record["id"])
    sent, failed, errors = 0, 0, []
    try:
        for index, email in enumerate(recipients):
            try:
                sender.send(build_message(email, record["subject"], record["body"], track))
                sent += 1
            except (smtplib.SMTPException, OSError) as error:
                failed += 1
                if len(errors) < 20:
                    errors.append(f"{email}: {error}")
            if index % 10 == 9:
                _update_campaign(record["id"], sent=sent, failed=failed, errors=errors)
            if sender.config["host"]:
                time.sleep(SEND_DELAY_SECONDS)
    finally:
        sender.close()
        _update_campaign(
            record["id"],
            sent=sent,
            failed=failed,
            errors=errors,
            status="sent" if sent else "failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
