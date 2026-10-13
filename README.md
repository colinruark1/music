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
| `/player` | Phone player, rendered from `design/project/Player.dc.html` |
| `POST /api/subscribe` | Newsletter sign-up, body `{"email": "..."}` |
| `/api/subscribers` | Everyone who has signed up |
| `/api/health` | Returns `{"ok": true}` |

The server reads the design files on every request, so a refresh picks up any
edit to them. Sign-ups are stored in `server/data/subscribers.json`, which is
not committed.

This is a temporary development backend: it listens on localhost only, has no
login, and keeps its data in a JSON file.
