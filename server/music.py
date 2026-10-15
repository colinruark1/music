"""The Music catalog the admin manages, stored in server/data/music.json.

Until an admin saves a change, the catalog is the set of cards in the
design's Music.dc.html and the pages render exactly as designed. After that,
the cards in each page's Music grid are rebuilt from music.json.
"""

import html
import re
import secrets

from pages import render_page
from store import LOCK, exists, read_json, write_json

FILE = "music.json"
DEFAULT_LINK_LABEL = "Stream / Download"

_ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.S)
_GRID_RE = re.compile(
    r'(<section id="music".*?<div style="display: grid[^>]*>)(.*?)(\n</div>\n</section>)', re.S
)
# Only plain web links and files this site serves; never javascript: and friends.
_SAFE_URL_RE = re.compile(r"^(https?://[^\s\"'<>]+|/(media|assets)/[\w.\-]+|#[\w\-]*)$")

_CARD = """
<article style="display: flex; flex-direction: column; gap: 12px">
<img src="{cover}" alt="{cover_alt}" style="display: block; width: 100%; aspect-ratio: 1 / 1; object-fit: cover; object-position: 50% 50%; background: #546067; box-sizing: border-box; border: 6px solid #FAFAF7">
<div style="font-family: 'Instrument Serif', Georgia, serif; font-size: 28px; line-height: 1.1">{title}</div>
<a href="{link}"{target} style="align-self: flex-start; padding: 10px 0; font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif; font-weight: 600; font-size: 18px; letter-spacing: 0.14em; text-transform: uppercase">{link_label}</a>
</article>
"""


def safe_url(url):
    return isinstance(url, str) and bool(_SAFE_URL_RE.match(url.strip()))


def _design_tracks():
    page = render_page("Music.dc.html")
    grid = _GRID_RE.search(page)
    tracks = []
    for index, article in enumerate(_ARTICLE_RE.findall(grid.group(2) if grid else "")):
        img = re.search(r'<img src="([^"]*)" alt="([^"]*)"', article)
        title = re.search(r"<div[^>]*>(.*?)</div>", article, re.S)
        link = re.search(r'<a href="([^"]*)"[^>]*>(.*?)</a>', article, re.S)
        tracks.append(
            {
                "id": f"design-{index + 1}",
                "title": html.unescape(title.group(1).strip()) if title else "",
                "cover": html.unescape(img.group(1)) if img else "",
                "cover_alt": html.unescape(img.group(2)) if img else "",
                "link": html.unescape(link.group(1)) if link else "#music",
                "link_label": html.unescape(link.group(2).strip()) if link else DEFAULT_LINK_LABEL,
            }
        )
    return tracks


def load():
    return read_json(FILE, None) if exists(FILE) else _design_tracks()


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
    with LOCK:
        tracks = load()
        track = {"id": secrets.token_hex(6), **fields}
        tracks.insert(0, track)
        write_json(FILE, tracks)
        return track


def update(track_id, fields):
    with LOCK:
        tracks = load()
        for track in tracks:
            if track["id"] == track_id:
                track.update(fields)
                write_json(FILE, tracks)
                return track
        return None


def delete(track_id):
    with LOCK:
        tracks = load()
        kept = [t for t in tracks if t["id"] != track_id]
        if len(kept) == len(tracks):
            return False
        write_json(FILE, kept)
        return True


def move(track_id, offset):
    with LOCK:
        tracks = load()
        index = next((i for i, t in enumerate(tracks) if t["id"] == track_id), None)
        if index is None:
            return False
        target = max(0, min(len(tracks) - 1, index + offset))
        tracks.insert(target, tracks.pop(index))
        write_json(FILE, tracks)
        return True


def find(track_id):
    return next((t for t in load() if t["id"] == track_id), None)


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
    """Swap the page's Music grid for the saved catalog, if there is one."""
    if not exists(FILE):
        return page
    grid = _GRID_RE.search(page)
    if not grid:
        return page
    tracks = load()[:limit] if limit else load()
    cards = render_cards(tracks) + "\n" if tracks else (
        '\n<p style="margin: 0; color: #C3C9CA">New music is on the way.</p>\n'
    )
    return page[: grid.start(2)] + "\n" + cards + page[grid.end(2):]
