# music
Getting Started

The Megan Faith site: public pages rendered from the design files in
`design/project/`, a newsletter sign-up, and an admin app at `/login` for
sending newsletters and managing the Music section. Data lives in Supabase
(project `xrakfsbzwzchnplfjney`). The site is hosted on Vercel. Python 3,
standard library only.

| URL | What it is |
| --- | --- |
| `/` | Home page, rendered from `design/project/Main.dc.html` |
| `/music` | Music page, rendered from `design/project/Music.dc.html` |
| `/tour` | Tour page, rendered from `design/project/Tour.dc.html` |
| `/about` | About page, rendered from `design/project/About.dc.html` |
| `/subscribe` | Subscribe page, rendered from `design/project/Subscribe.dc.html` |
| `/player` | Phone player, rendered from `design/project/Player.dc.html` |
| `/privacy` | Privacy policy, rendered from `design/project/Privacy.dc.html`. Linked from every footer and both sign-up forms |
| `POST /api/subscribe` | Newsletter sign-up, body `{"email": "..."}` |
| `/unsubscribe` | Where the unsubscribe link in every newsletter lands |
| `/login` | Admin login (not linked from the site) |
| `/admin` | Admin app: send newsletters, manage the Music catalog, see subscribers |
| `/api/health` | Returns `{"ok": true}` and any settings that are missing |

## Settings

| Variable | What it's for |
| --- | --- |
| `SUPABASE_SECRET_KEY` | **Required.** Supabase dashboard → Project Settings → API Keys → Secret key (`sb_secret_…`; the legacy `service_role` key also works). Server-only: never put it in browser code. |
| `SESSION_SECRET` | **Required.** A long random string (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`). Signs admin logins and unsubscribe links. Don't change it once emails have gone out, or their unsubscribe links stop working. |
| `SUPABASE_URL` | Defaults to `https://xrakfsbzwzchnplfjney.supabase.co`. |
| `SITE_URL` | The site's public address, used in email links and images. Defaults to the Vercel production URL. Set it when you add your own domain. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SECURITY`, `MAIL_FROM` | Your email provider (see [Sending email](#sending-email)). |

On Vercel, add these under Project → Settings → Environment Variables, then
redeploy. Locally, put them in `.env.local` at the repo root (gitignored):

```sh
SUPABASE_SECRET_KEY=sb_secret_...
SESSION_SECRET=...
```

## One-time Supabase setup

1. **Create the tables.** In the Supabase dashboard, open SQL Editor and run
   the contents of `supabase/migrations/20261015000000_site_data.sql`. Or use
   the CLI: `supabase login`, then `supabase link --project-ref xrakfsbzwzchnplfjney`,
   then `supabase db push`. This creates the tables, the send functions, the
   public `media` bucket for uploads, and the four starter tracks from the
   design.
2. **Turn off public sign-ups.** Go to Authentication → Sign In / Providers
   and switch off "Allow new users to sign up". Admins are added by hand
   (step 3), so nobody else needs an account.
3. **Add an admin.** With `.env.local` filled in:

   ```sh
   python3 server/app.py add-admin megan@example.com   # asks for a password (9+ characters)
   python3 server/app.py list-admins
   python3 server/app.py remove-admin megan@example.com
   ```

   `add-admin` creates the Supabase Auth login, or resets its password, and
   adds the account to the `admins` table. Only people in that table can use
   `/admin`, and removing someone signs them out right away.

Every table has row-level security turned on with no policies, so the
publishable key can't read or change anything. Only the server, using the
secret key, can.

## Run it locally

```sh
python3 server/app.py
```

Then open http://127.0.0.1:8000 (set `PORT` for a different port). This uses
the same Supabase project as the live site, so sign-ups and tracks you add
locally are real. To experiment safely, run a local Supabase instead with
`supabase start` (needs Docker; ports are set to 553xx in
`supabase/config.toml`). Then point `SUPABASE_URL` at `http://127.0.0.1:55321`
and use the secret key it prints.

The server reads the design files on every request, so a refresh picks up any
edit to them.

## Admin app

Log in at `/login` with an admin's email and password. Five wrong passwords
from the same network lock it out for 15 minutes. Logins last 12 hours.

**Music.** The Music grid on `/music` (all tracks) and on the home page (the
first four) is built from the `tracks` table. New tracks go to the top, and
the arrows reorder them. Cover art and audio files upload straight from the
browser to the `media` storage bucket.

**Newsletter.** Write a subject and message, optionally feature a track, send
yourself a test, then send to everyone. Each subscriber gets their own email
with an unsubscribe link, and mail apps get a one-click unsubscribe header.
Emails go out in batches of 20 while the admin page is open. If the page is
closed partway through, the send picks up where it stopped the next time
`/admin` is opened. Anyone who unsubscribes during a send is skipped.

**Subscribers.** Search the list, remove people, or export it as CSV.

## Sending email

Email goes out through any SMTP provider, such as Postmark, Resend, Mailgun,
Amazon SES, or a Gmail app password:

```sh
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
MAIL_FROM="Megan Faith <hello@yourdomain.com>"
```

`SMTP_SECURITY` is `starttls` (default), `ssl` (usually port 465) or `none`.
Without SMTP settings, the live site can't send and the admin page says so.
A local server saves each email as an `.eml` file in `server/data/outbox/`
instead, so you can open it and check how it looks.

## Deploying

Vercel builds from `main`. `vercel.json` copies `design/assets/` and
`server/static/` into `public/` as plain files (`server/build.py`), and sends
every other request to the Python function in `api/index.py`, which runs
`server/app.py`.
