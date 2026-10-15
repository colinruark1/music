# music
Getting Started

## Run the site locally

Needs Python 3 and nothing else.

```sh
python3 server/app.py
```

Then open http://127.0.0.1:8000. Set `PORT` to use a different port.

| URL | What it is |
| --- | --- |
| `/` | Home page, rendered from `design/project/Main.dc.html` |
| `/music` | Music page, rendered from `design/project/Music.dc.html` |
| `/tour` | Tour page, rendered from `design/project/Tour.dc.html` |
| `/about` | About page, rendered from `design/project/About.dc.html` |
| `/subscribe` | Subscribe page, rendered from `design/project/Subscribe.dc.html` |
| `/player` | Phone player, rendered from `design/project/Player.dc.html` |
| `POST /api/subscribe` | Newsletter sign-up, body `{"email": "..."}` |
| `/unsubscribe` | Where the unsubscribe link in every newsletter lands |
| `/login` | Admin login (not linked from the site) |
| `/admin` | Admin app: send newsletters, manage the Music catalog, see subscribers |
| `/api/health` | Returns `{"ok": true}` |

The server reads the design files on every request, so a refresh picks up any
edit to them. Everything the site saves lives in `server/data/`, which is not
committed: sign-ups, admin accounts, the Music catalog, uploaded files
(`media/`), the send history and the outbox.

## Admin app

Create an admin account first (you'll be asked for a password, 10+ characters):

```sh
python3 server/app.py add-admin megan      # also resets an existing password
python3 server/app.py list-admins
python3 server/app.py remove-admin megan
```

Then go to http://127.0.0.1:8000/login. Five wrong passwords lock that
computer out for 15 minutes. Sessions last 12 hours and end when the server
restarts.

**Music.** Until you save a change, the catalog is the four cards in the
design. After that, the Music grid on `/music` (all tracks) and on the home
page (the first four) is built from the admin list. New tracks go to the top.
Cover art and audio files you upload are served from `/media/`.

**Newsletter.** Write a subject and message, optionally feature a track, send
yourself a test, then send to everyone. Each subscriber gets their own email
with an unsubscribe link, and mail apps get a one-click unsubscribe header.

Email isn't sent until you connect a mail provider (any SMTP service, such as
Postmark, Mailgun, Amazon SES, or a Gmail app password). Until then, each email
is saved as an `.eml` file in `server/data/outbox/` so you can open it and
check how it looks. To send for real:

```sh
SMTP_HOST=smtp.example.com SMTP_PORT=587 \
SMTP_USERNAME=... SMTP_PASSWORD=... \
MAIL_FROM="Megan Faith <hello@yourdomain.com>" \
SITE_URL=https://yourdomain.com \
python3 server/app.py
```

`SMTP_SECURITY` is `starttls` (default), `ssl` (usually port 465) or `none`.
`SITE_URL` must be the public address of the site, or the links, cover art and
unsubscribe links in emails won't work for subscribers.

This is still a development backend: it listens on localhost only and keeps
its data in JSON files. Before putting it on the internet, run it behind HTTPS
and set `COOKIE_SECURE=1` so the login cookie is only sent over HTTPS.
