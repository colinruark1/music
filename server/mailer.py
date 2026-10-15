"""Newsletter emails: compose, send through SMTP, and track each send.

Configured with environment variables:

    SMTP_HOST, SMTP_PORT (587), SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_SECURITY (starttls | ssl | none, default starttls),
    MAIL_FROM ("Megan Faith <hello@example.com>"),
    SITE_URL (the public address of the site, used for links and images).

Without SMTP_HOST, a local server writes each email to
server/data/outbox/<send id>/ as an .eml file instead of sending it. On
Vercel there's no disk to write to, so sending needs SMTP.

Sends go out in batches: the admin page calls send_batch() repeatedly until
everyone has been sent to, so no single request runs long enough to time out.
"""

import hashlib
import hmac
import html
import re
import smtplib
import ssl
import time
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from urllib.parse import urlencode

import config
import db

OUTBOX_DIR = config.DATA_DIR / "outbox"
ARTIST = "Megan Faith"
BATCH_SIZE = 20
SEND_DELAY_SECONDS = 0.2  # stay well under typical SMTP rate limits

# Long unsubscribe URLs must stay on one header line, not get MIME-encoded.
_POLICY = policy.SMTP.clone(max_line_length=998)
_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_SUMMARY_FIELDS = (
    "id,subject,track_title,sent_by,mode,status,created_at,finished_at,recipients,sent,failed,remaining,errors"
)


def settings():
    port = config.get("PORT", "8000")
    vercel_host = config.get("VERCEL_PROJECT_PRODUCTION_URL")
    default_site = f"https://{vercel_host}" if vercel_host else f"http://127.0.0.1:{port}"
    return {
        "host": config.get("SMTP_HOST"),
        "port": int(config.get("SMTP_PORT", "587")),
        "username": config.get("SMTP_USERNAME"),
        "password": config.get("SMTP_PASSWORD"),
        "security": config.get("SMTP_SECURITY", "starttls").lower(),
        "from": config.get("MAIL_FROM", f"{ARTIST} <newsletter@localhost>"),
        "site_url": config.get("SITE_URL", default_site).rstrip("/"),
    }


def mode():
    """'smtp' sends for real, 'outbox' writes files locally, 'off' can't send."""
    if settings()["host"]:
        return "smtp"
    return "off" if config.ON_VERCEL else "outbox"


def status():
    current = settings()
    return {"mode": mode(), "from": current["from"], "site_url": current["site_url"], "outbox": str(OUTBOX_DIR)}


# ---------- unsubscribe links ----------

def unsubscribe_token(email):
    message = f"unsubscribe:{email.lower()}".encode("utf-8")
    return hmac.new(config.SESSION_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


def check_unsubscribe_token(email, token):
    if not config.SESSION_SECRET or not email:
        return False
    return hmac.compare_digest(unsubscribe_token(email), token or "")


def unsubscribe_url(email):
    query = urlencode({"email": email, "token": unsubscribe_token(email)})
    return f"{settings()['site_url']}/unsubscribe?{query}"


# ---------- building an email ----------

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
    current = settings()
    site = current["site_url"]
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
    message["From"] = current["from"]
    message["To"] = to
    message["Date"] = formatdate(localtime=True)
    domain = parseaddr(current["from"])[1].rpartition("@")[2] or None
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


# ---------- delivery ----------

class _Sender:
    """One SMTP connection reused across a batch, or a local outbox folder."""

    def __init__(self, outbox_name):
        self.config = settings()
        self.mode = mode()
        self.outbox = OUTBOX_DIR / outbox_name
        self.smtp = None

    def _connect(self):
        c = self.config
        if c["security"] == "ssl":
            smtp = smtplib.SMTP_SSL(c["host"], c["port"], timeout=20, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(c["host"], c["port"], timeout=20)
            if c["security"] == "starttls":
                smtp.starttls(context=ssl.create_default_context())
        if c["username"]:
            smtp.login(c["username"], c["password"])
        return smtp

    def send(self, message):
        if self.mode == "outbox":
            self.outbox.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^\w.@-]", "_", message["To"]) + ".eml"
            (self.outbox / name).write_bytes(bytes(message))
            return
        if self.mode == "off":
            raise smtplib.SMTPException("No email provider is connected (set SMTP_HOST).")
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


# ---------- sends ----------

def campaigns():
    return db.select("campaign_summary", select=_SUMMARY_FIELDS, order="created_at.desc", limit=50)


def campaign(campaign_id):
    rows = db.select("campaign_summary", select=_SUMMARY_FIELDS, id=db.eq(campaign_id))
    return rows[0] if rows else None


def start_campaign(subject, body, track, sent_by):
    """Queue a send to every subscriber. Returns (summary, error)."""
    if mode() == "off":
        return None, "Connect an email provider first (see the README: SMTP settings)."
    snapshot = None
    if track:
        snapshot = {k: track[k] for k in ("id", "title", "cover", "cover_alt", "link", "link_label")}
    try:
        campaign_id = db.rpc(
            "start_campaign",
            p_subject=subject, p_body=body, p_track=snapshot, p_sent_by=sent_by, p_mode=mode(),
        )
    except db.DatabaseError as error:
        if error.status == 409 or "campaigns_one_sending" in str(error):
            return None, "Another email is still sending. Wait for it to finish."
        if error.status == 400:  # the function's own messages (nobody signed up, etc.)
            return None, str(error)
        raise
    return campaign(campaign_id), None


def send_batch(campaign_id):
    """Send to the next batch of recipients. Returns the updated summary."""
    rows = db.select("campaigns", select="id,subject,body,track,status", id=db.eq(campaign_id))
    if not rows:
        return None
    record = rows[0]
    if record["status"] != "sending":
        return campaign(campaign_id)

    claimed = db.rpc("claim_deliveries", p_campaign=campaign_id, p_limit=BATCH_SIZE) or []
    sender = _Sender(campaign_id)
    try:
        for index, delivery in enumerate(claimed):
            email = delivery["email"]
            try:
                sender.send(build_message(email, record["subject"], record["body"], record["track"]))
                result = {"status": "sent", "error": None}
            except (smtplib.SMTPException, OSError) as error:
                result = {"status": "failed", "error": str(error)[:300]}
            db.update(
                "deliveries",
                {**result, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                campaign_id=db.eq(campaign_id),
                email=db.eq(email),
            )
            if sender.mode == "smtp" and index < len(claimed) - 1:
                time.sleep(SEND_DELAY_SECONDS)
    finally:
        sender.close()

    if len(claimed) < BATCH_SIZE:
        db.rpc("finish_campaign", p_campaign=campaign_id)
    return campaign(campaign_id)
