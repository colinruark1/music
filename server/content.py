"""Editable copy for the site's shared sections (hero, shows, about, subscribe,
links and footer), stored in the Supabase `site_content` table, one row per
section. The admin's Home page tab edits it.

The design files mark what can change:

    data-edit="hero.title"              the element's text
    data-edit-href / -src / -alt        that attribute
    data-edit-hide="links.tiktok"       drop the element when that field is empty
    data-edit-list="shows.dates"        a list: each child element is one item,
                                        and data-edit-field[-href|-hide]="place"
                                        marks the parts of an item

A section nobody has saved keeps the design's own text. The same section shows
everywhere it's marked, so the shows on the home page and /tour stay in step.
"""

import html
import re
import sys
from datetime import datetime, timezone

import db
from pages import render_page

MIGRATION = "supabase/migrations/20261019010000_site_content.sql"
# The link preview photo until a hero photo is saved: the design's hero photo.
DEFAULT_PREVIEW = ("/assets/hero-polaroid.jpg", "Playing an acoustic guitar on a balcony in the evening sun")

# section -> (title, source page for the current text, fields)
# field -> (label, kind, max length, hint); a list's "max length" is its item count.
SECTIONS = {
    "hero": ("Top of the home page", "Main.dc.html", {
        "tagline": ("Small line above your name", "text", 200, "Song titles, a tour name…"),
        "title": ("Big title", "text", 80, ""),
        "subtitle": ("Line under the title", "text", 300, ""),
        "button_label": ("Button text", "text", 40, ""),
        "button_link": ("Button link", "link", 500, "#music scrolls to the songs. Or paste any https:// link."),
        "photo": ("Photo", "image", 1000, "A portrait photo looks best (7 wide by 8 tall)."),
        "photo_alt": ("Describe the photo", "text", 300, "Read aloud by screen readers."),
    }),
    "music": ("Music section", "Main.dc.html", {
        "intro": ("Line under the heading", "text", 300, "Also on /music. Songs are edited in the Music tab."),
    }),
    "shows": ("Shows", "Tour.dc.html", {
        "heading": ("Heading", "text", 60, ""),
        "intro": ("Line next to the heading", "text", 300, ""),
        "dates": ("Dates", "list", 30, {
            "date": ("Date", "text", 20, "Short, like Jun 14"),
            "place": ("Venue", "text", 120, ""),
            "town": ("Town, State", "text", 120, ""),
            "details": ("Time and details", "text", 120, "Like 8 PM · Back porch stage"),
            "button_label": ("Button text", "text", 40, ""),
            "button_link": ("Button link", "link", 500, "Tickets link, or /subscribe. Leave empty for no button."),
        }),
    }),
    "about": ("About", "About.dc.html", {
        "heading": ("Heading", "text", 60, ""),
        "quote": ("Quote", "text", 400, ""),
        "facts": ("Facts", "list", 10, {
            "title": ("Title", "text", 80, ""),
            "description": ("Description", "text", 300, ""),
        }),
    }),
    "subscribe": ("Subscribe section", "Subscribe.dc.html", {
        "heading": ("Heading", "text", 60, ""),
        "intro": ("Line under the heading", "text", 300, ""),
    }),
    "links": ("Links", "Main.dc.html", {
        "instagram": ("Instagram", "link", 500, "Leave empty to hide the Instagram links."),
        "tiktok": ("TikTok", "link", 500, "Leave empty to hide the TikTok links."),
        "streaming_label": ("Streaming link text", "text", 40, "Like Spotify"),
        "streaming_link": ("Streaming link", "link", 500, "Shows in the footer. Leave empty to hide it."),
        "booking_label": ("Booking link text", "text", 40, "Like Booking"),
        "booking_email": ("Booking email", "email", 254, "Shows in the footer. Leave empty to hide it."),
    }),
    "footer": ("Footer", "Main.dc.html", {
        "note": ("Note", "text", 300, ""),
    }),
}

_LINK_RE = re.compile(r"^(https?://[^\s\"'<>]+|/[^\s\"'<>]*|#[\w\-]*)$")
_IMAGE_RE = re.compile(r"^(https://[^\s\"'<>]+|/assets/[\w.\-]+)$")
_EMAIL_RE = re.compile(r"^[^@\s\"'<>]+@[^@\s\"'<>]+\.[^@\s\"'<>]+$")
_EDIT_TAG_RE = re.compile(r'<([a-zA-Z][\w-]*)\b[^>]*\sdata-edit[\w-]*="[^>]*>')
_ATTR_RE = re.compile(r'\s(data-edit[\w-]*)="([^"]*)"')
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


# ---------- saving ----------

def clean(section, data):
    """Validate a section from the admin form. Returns (value, error)."""
    if section not in SECTIONS:
        return None, "That section doesn't exist."
    if not isinstance(data, dict):
        return None, "Send the section as a JSON object."
    return _clean_fields(SECTIONS[section][2], data)


def _clean_fields(fields, data):
    value = {}
    for name, (label, kind, limit, extra) in fields.items():
        raw = data.get(name)
        if kind == "list":
            if not isinstance(raw, list):
                return None, f"{label}: send a list."
            items = []
            for item in raw:
                cleaned, error = _clean_fields(extra, item if isinstance(item, dict) else {})
                if error:
                    return None, f"{label}, item {len(items) + 1}: {error}"
                if any(cleaned.values()):  # skip blank rows
                    items.append(cleaned)
            if len(items) > limit:
                return None, f"{label}: up to {limit}."
            value[name] = items
            continue
        text = raw.strip() if isinstance(raw, str) else ""
        if len(text) > limit:
            return None, f"{label} is too long (up to {limit} characters)."
        if text and kind == "link" and not _LINK_RE.match(text):
            return None, f"{label} should start with https://, / or #."
        if text and kind == "image" and not _IMAGE_RE.match(text):
            return None, f"{label}: upload an image, or paste an https:// image link."
        if text and kind == "email" and not _EMAIL_RE.match(text):
            return None, f"{label} doesn't look like an email address."
        value[name] = " ".join(text.split())  # one line: the design has no room for breaks
    return value, None


def save(section, value, user):
    db.call("POST", "/rest/v1/site_content", {"on_conflict": "section"},
            {"section": section, "value": value, "updated_by": user,
             "updated_at": datetime.now(timezone.utc).isoformat()},
            {"Prefer": "resolution=merge-duplicates,return=minimal"})


def reset(section):
    """Forget a section's saved copy, so the design's text shows again."""
    db.delete("site_content", section=db.eq(section))


def load_saved():
    try:
        rows = db.select("site_content", select="section,value")
    except db.DatabaseError as error:
        if "site_content" in str(error):
            raise db.DatabaseError(f"Run {MIGRATION} in the Supabase SQL Editor first.") from None
        raise
    return {row["section"]: row["value"] for row in rows if row["section"] in SECTIONS}


def for_admin():
    """Each section's fields and current values (saved, else the design's)."""
    saved = load_saved()
    sections = []
    for name, (title, source, fields) in SECTIONS.items():
        current = saved.get(name) or _design_values(name, source, fields)
        sections.append({
            "name": name,
            "title": title,
            "saved": name in saved,
            "fields": _describe(fields),
            "value": {field: current.get(field, [] if spec[1] == "list" else "") for field, spec in fields.items()},
        })
    return sections


def _describe(fields):
    described = []
    for name, (label, kind, limit, extra) in fields.items():
        entry = {"name": name, "label": label, "kind": kind, "max": limit}
        if kind == "list":
            entry["fields"] = _describe(extra)
        else:
            entry["hint"] = extra
        described.append(entry)
    return described


# ---------- reading the design's current text ----------

def _design_values(section, source, fields):
    page = render_page(source)
    found = _read_marks(page, "data-edit")
    value = {}
    for name, (_, kind, _, extra) in fields.items():
        key = f"{section}.{name}"
        if kind == "list":
            value[name] = []
            container = _find_mark(page, "data-edit-list", key)
            if container:
                for start, end in _children(page, *container[:4]):
                    item = _read_marks(page[start:end], "data-edit-field")
                    value[name].append({field: item.get(field, "") for field in extra})
        elif name == "booking_email":
            href = found.get("links.booking_href", "")
            value[name] = href[len("mailto:"):] if href.startswith("mailto:") else ""
        else:
            value[name] = found.get(key, "")
    return value


def _read_marks(fragment, prefix):
    """{field: current text or attribute} for each mark in a piece of markup."""
    found = {}
    for match in _EDIT_TAG_RE.finditer(fragment):
        tag = match.group(0)
        attrs = dict(_ATTR_RE.findall(tag))
        for suffix, attr in (("-href", "href"), ("-src", "src"), ("-alt", "alt")):
            if prefix + suffix in attrs:
                current = re.search(rf'\s{attr}="([^"]*)"', tag)
                found[attrs[prefix + suffix]] = html.unescape(current.group(1)) if current else ""
        if prefix in attrs:
            close_start, _ = _element_end(fragment, match.start(), match.group(1))
            inner = _TAG_STRIP_RE.sub("", fragment[match.end():close_start])
            found[attrs[prefix]] = " ".join(html.unescape(inner).split())
    return found


# ---------- applying it to a page ----------

def apply_content(page, site_url):
    """Swap the marked text on a page for the copy saved in the admin, and
    add the link preview tags."""
    try:
        saved = load_saved()
    except db.DatabaseError as error:
        print(f"Site content unavailable, showing the design's text: {error}", file=sys.stderr)
        saved = {}
    page = _add_preview(page, saved.get("hero", {}), site_url)
    if not saved:
        return page
    links = saved.get("links")
    if links and "booking_email" in links:
        links["booking_href"] = f"mailto:{links['booking_email']}" if links["booking_email"] else ""

    def value_of(key):
        section, _, field = key.partition(".")
        return saved.get(section, {}).get(field)

    return _fill(_fill_lists(page, value_of), value_of, "data-edit")


def _add_preview(page, hero, site_url):
    """Tell link previews (iMessage, Slack, Facebook…) which photo and title
    to show, instead of letting them pick a picture from the page."""
    photo = hero.get("photo") or DEFAULT_PREVIEW[0]
    alt = hero.get("photo_alt") if hero.get("photo") else DEFAULT_PREVIEW[1]
    if not photo.startswith("http"):
        photo = site_url + photo
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    tags = [
        ("og:type", "website"),
        ("og:title", html.unescape(title.group(1)) if title else "Megan Faith"),
        ("og:image", photo),
        ("og:image:alt", alt or ""),
    ]
    if hero.get("subtitle"):
        tags.append(("og:description", hero["subtitle"]))
    meta = "".join(f'<meta property="{name}" content="{html.escape(value)}">\n' for name, value in tags)
    meta += '<meta name="twitter:card" content="summary_large_image">\n'
    return page.replace("</head>", meta + "</head>", 1)


def _fill_lists(page, value_of):
    out, pos = [], 0
    while True:
        container = _find_mark(page, "data-edit-list", None, pos)
        if not container:
            break
        tag_start, tag_end, close_start, close_end, key, empty = container
        items = value_of(key)
        if items is None:
            out.append(page[pos:close_end])
            pos = close_end
            continue
        children = list(_children(page, tag_start, tag_end, close_start, close_end))
        out.append(page[pos:tag_end])
        if items and children:
            first, last = page[slice(*children[0])], page[slice(*children[-1])]
            rendered = [
                # The design's last item can differ (a closing border), so it
                # is the pattern for the last row.
                _fill(last if i == len(items) - 1 else first, lambda f, item=item: item.get(f, ""), "data-edit-field")
                for i, item in enumerate(items)
            ]
            out.append("\n\n" + "\n\n".join(rendered) + "\n\n")
        elif empty:
            out.append(f'\n<p style="margin: 0; padding: 22px 0">{empty}</p>\n')
        out.append(page[close_start:close_end])
        pos = close_end
    out.append(page[pos:])
    return "".join(out)


def _fill(fragment, value_of, prefix):
    """Fill each mark that has a value; leave the rest as the design has them."""
    out, pos = [], 0
    for match in _EDIT_TAG_RE.finditer(fragment):
        if match.start() < pos:  # inside an element whose text was replaced
            continue
        tag, name = match.group(0), match.group(1)
        attrs = dict(_ATTR_RE.findall(tag))
        if not any(attr == prefix or attr in (prefix + "-href", prefix + "-src", prefix + "-alt", prefix + "-hide") for attr in attrs):
            continue
        out.append(fragment[pos:match.start()])
        if prefix + "-hide" in attrs and value_of(attrs[prefix + "-hide"]) == "":
            pos = _element_end(fragment, match.start(), name)[1]
            continue
        for suffix, attr in (("-href", "href"), ("-src", "src"), ("-alt", "alt")):
            value = value_of(attrs[prefix + suffix]) if prefix + suffix in attrs else None
            if value is not None:
                tag = re.sub(rf'\s{attr}="[^"]*"', lambda _: f' {attr}="{html.escape(value)}"', tag, count=1)
        text = value_of(attrs[prefix]) if prefix in attrs else None
        if text is None:
            out.append(tag)
            pos = match.end()
        else:
            close_start, close_end = _element_end(fragment, match.start(), name)
            out.append(tag + html.escape(text) + fragment[close_start:close_end])
            pos = close_end
    out.append(fragment[pos:])
    return "".join(out)


# ---------- finding elements ----------

def _element_end(page, start, name):
    """(start, end) of the closing tag of the element that opens at `start`."""
    depth = 0
    for match in re.finditer(rf"<(/?){name}\b[^>]*>", page[start:]):
        depth += -1 if match.group(1) else 1
        if depth == 0:
            return start + match.start(), start + match.end()
    raise ValueError(f"<{name}> at {start} is never closed")


def _find_mark(page, attr, key, pos=0):
    """The next element with attr="key" (any key if None): its tag and close
    positions, its key, and its data-edit-empty text."""
    for match in re.finditer(rf'<([a-zA-Z][\w-]*)\b[^>]*\s{attr}="([^"]*)"[^>]*>', page[pos:]):
        if key is None or match.group(2) == key:
            start = pos + match.start()
            close_start, close_end = _element_end(page, start, match.group(1))
            empty = re.search(r'\sdata-edit-empty="([^"]*)"', match.group(0))
            return start, pos + match.end(), close_start, close_end, match.group(2), empty.group(1) if empty else ""
    return None


def _children(page, tag_start, tag_end, close_start, close_end):
    """(start, end) of each element directly inside a container."""
    pos = tag_end
    while True:
        match = re.compile(r"<([a-zA-Z][\w-]*)\b[^>]*>").search(page, pos, close_start)
        if not match:
            return
        end = _element_end(page, match.start(), match.group(1))[1]
        yield match.start(), end
        pos = end
