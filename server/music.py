"""The Music catalog the admin manages, stored in the Supabase `tracks` table.

The cards in each page's Music grid are rebuilt from the table. If Supabase
can't be reached, the page falls back to the cards in the design.
"""

import html
import re
import secrets
import sys
from pathlib import Path

import db

DEFAULT_LINK_LABEL = "Stream / Download"
MEDIA_BUCKET = "media"
UPLOAD_TYPES = {
    ".jpg": 10_000_000, ".jpeg": 10_000_000, ".png": 10_000_000, ".webp": 10_000_000,
    ".mp3": 60_000_000, ".m4a": 60_000_000, ".wav": 60_000_000,
}

_GRID_RE = re.compile(
    r'(<section id="music".*?<div style="display: grid[^>]*>)(.*?)(\n</div>\n</section>)', re.S
)
# Only plain web links and files this site serves; never javascript: and friends.
_SAFE_URL_RE = re.compile(r"^(https?://[^\s\"'<>]+|/assets/[\w.\-]+|#[\w\-]*)$")
_FIELDS = "id,position,title,cover,cover_alt,link,link_label"

_CARD = """
<article style="display: flex; flex-direction: column; gap: 12px">
<img src="{cover}" alt="{cover_alt}" style="display: block; width: 100%; aspect-ratio: 1 / 1; object-fit: cover; object-position: 50% 50%; background: #546067; box-sizing: border-box; border: 6px solid #FAFAF7">
<div style="font-family: 'Instrument Serif', Georgia, serif; font-size: 28px; line-height: 1.1">{title}</div>
<a href="{link}"{target} style="align-self: flex-start; padding: 10px 0; font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif; font-weight: 600; font-size: 18px; letter-spacing: 0.14em; text-transform: uppercase">{link_label}</a>
</article>
"""


def safe_url(url):
    return isinstance(url, str) and bool(_SAFE_URL_RE.match(url.strip()))


def load():
    return db.select("tracks", select=_FIELDS, order="position.asc,created_at.desc")


def find(track_id):
    rows = db.select("tracks", select=_FIELDS, id=db.eq(track_id))
    return rows[0] if rows else None


def clean(data):
    """Validate a track from the admin form. Returns (track_fields, error)."""
    if not isinstance(data, dict):
        return None, "Send the track as a JSON object."
    fields = {
        key: data.get(key, "").strip() if isinstance(data.get(key, ""), str) else ""
        for key in ("title", "cover", "cover_alt", "link", "link_label")
    }
    if not fields["title"]:
        return None, "Give the track a title."
    if len(fields["title"]) > 120 or len(fields["cover_alt"]) > 300 or len(fields["link_label"]) > 40:
        return None, "One of the fields is too long."
    if not safe_url(fields["cover"]):
        return None, "Upload cover art, or paste an https:// image link."
    if not safe_url(fields["link"]):
        return None, "Upload an audio file, or paste an https:// streaming link."
    fields["link_label"] = fields["link_label"] or DEFAULT_LINK_LABEL
    return fields, None


def add(fields):
    """New tracks go to the top of the list."""
    first = db.select("tracks", select="position", order="position.asc", limit=1)
    position = (first[0]["position"] - 1) if first else 0
    return db.insert("tracks", {**fields, "position": position})[0]


def update(track_id, fields):
    rows = db.update("tracks", fields, id=db.eq(track_id))
    return rows[0] if rows else None


def delete(track_id):
    return bool(db.delete("tracks", id=db.eq(track_id)))


def move(track_id, offset):
    tracks = load()
    index = next((i for i, t in enumerate(tracks) if t["id"] == track_id), None)
    if index is None:
        return False
    target = max(0, min(len(tracks) - 1, index + offset))
    tracks.insert(target, tracks.pop(index))
    # Renumber, and only write the rows whose position changed.
    for position, track in enumerate(tracks):
        if track["position"] != position:
            db.update("tracks", {"position": position}, id=db.eq(track["id"]))
    return True


def upload_target(name, size):
    """Where the browser should upload a file. Returns (urls, error)."""
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_TYPES:
        return None, "Upload a JPG, PNG or WebP image, or an MP3, M4A or WAV file."
    if not isinstance(size, int) or size <= 0 or size > UPLOAD_TYPES[ext]:
        return None, f"Files of this type can be up to {UPLOAD_TYPES[ext] // 1_000_000} MB."
    path = f"{secrets.token_hex(8)}{'.jpg' if ext == '.jpeg' else ext}"
    return {
        "upload_url": db.signed_upload_url(MEDIA_BUCKET, path),
        "url": db.public_url(MEDIA_BUCKET, path),
    }, None


def render_cards(tracks):
    cards = []
    for track in tracks:
        external = track["link"].startswith("http")
        cards.append(
            _CARD.format(
                cover=html.escape(track["cover"]),
                cover_alt=html.escape(track["cover_alt"]),
                title=html.escape(track["title"]),
                link=html.escape(track["link"]),
                target=' target="_blank" rel="noopener"' if external else "",
                link_label=html.escape(track["link_label"]),
            )
        )
    return "".join(cards)


def apply_catalog(page, limit=None):
    """Swap the page's Music grid for the catalog in Supabase."""
    grid = _GRID_RE.search(page)
    if not grid:
        return page
    try:
        tracks = load()
    except db.DatabaseError as error:
        print(f"Music catalog unavailable, showing the design's cards: {error}", file=sys.stderr)
        return page
    tracks = tracks[:limit] if limit else tracks
    cards = render_cards(tracks) + "\n" if tracks else (
        '\n<p style="margin: 0; color: #C3C9CA">New music is on the way.</p>\n'
    )
    return page[: grid.start(2)] + "\n" + cards + page[grid.end(2):]
