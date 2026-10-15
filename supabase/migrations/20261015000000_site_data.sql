-- Megan Faith site: newsletter sign-ups, Music catalog, admin accounts,
-- newsletter sends, and the media bucket for uploaded cover art and audio.
--
-- Every table has row-level security on and no policies, so the public
-- (publishable / anon) key can't read or write anything. The site's server
-- uses the secret key, which bypasses RLS.

-- ---------- newsletter sign-ups ----------

create table public.subscribers (
  id bigint generated always as identity primary key,
  email text not null unique check (email = lower(email) and char_length(email) <= 254),
  subscribed_at timestamptz not null default now()
);

-- ---------- Music catalog ----------

create table public.tracks (
  id uuid primary key default gen_random_uuid(),
  position integer not null default 0,
  title text not null check (char_length(title) between 1 and 120),
  cover text not null,
  cover_alt text not null default '' check (char_length(cover_alt) <= 300),
  link text not null,
  link_label text not null default 'Stream / Download' check (char_length(link_label) <= 40),
  created_at timestamptz not null default now()
);
create index tracks_position on public.tracks (position);

-- The four cards from the design, so the site looks the same until the
-- artist replaces them.
insert into public.tracks (position, title, cover, cover_alt, link) values
  (1, '[Song Title One]', '/assets/cover-4.jpg', 'On stage with an acoustic guitar under a marquee sign reading Megan Faith', '#music'),
  (2, '[Song Title Two]', '/assets/cover-2-palms.jpg', 'Tall palm trees above a busy beach, with boats on the ocean behind', '#music'),
  (3, '[Song Title Three]', '/assets/cover-3-shore.jpg', 'Sitting barefoot on a mossy rock at the water''s edge', '#music'),
  (4, '[Song Title Four]', '/assets/cover-4-guitar.jpg', 'A hand in beaded bracelets strumming an acoustic guitar', '#music');

-- ---------- admins ----------

-- Who may use /admin. Passwords live in Supabase Auth; a user must also be
-- listed here. Add one with: python3 server/app.py add-admin you@example.com
create table public.admins (
  user_id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  added_at timestamptz not null default now()
);

-- Failed logins, for the lockout. `client` is a keyed hash of the visitor's
-- IP address, never the address itself.
create table public.login_failures (
  id bigint generated always as identity primary key,
  client text not null,
  failed_at timestamptz not null default now()
);
create index login_failures_client_time on public.login_failures (client, failed_at);

-- ---------- newsletter sends ----------

create table public.campaigns (
  id uuid primary key default gen_random_uuid(),
  subject text not null,
  body text not null,
  track jsonb,                -- copy of the featured track at send time
  sent_by text not null,
  mode text not null,         -- 'smtp' or 'outbox'
  status text not null default 'sending' check (status in ('sending', 'sent', 'failed')),
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
-- Only one send at a time.
create unique index campaigns_one_sending on public.campaigns ((true)) where status = 'sending';

-- One row per recipient, so a send can stop and pick up where it left off.
create table public.deliveries (
  campaign_id uuid not null references public.campaigns (id) on delete cascade,
  email text not null,
  status text not null default 'pending'
    check (status in ('pending', 'sending', 'sent', 'failed', 'skipped')),
  error text,
  updated_at timestamptz not null default now(),
  primary key (campaign_id, email)
);
create index deliveries_open on public.deliveries (campaign_id) where status in ('pending', 'sending');

alter table public.subscribers enable row level security;
alter table public.tracks enable row level security;
alter table public.admins enable row level security;
alter table public.login_failures enable row level security;
alter table public.campaigns enable row level security;
alter table public.deliveries enable row level security;

create view public.campaign_summary with (security_invoker = true) as
select
  c.id,
  c.subject,
  c.body,
  c.track ->> 'title' as track_title,
  c.sent_by,
  c.mode,
  c.status,
  c.created_at,
  c.finished_at,
  count(d.email) filter (where d.status <> 'skipped')::int as recipients,
  count(d.email) filter (where d.status = 'sent')::int as sent,
  count(d.email) filter (where d.status = 'failed')::int as failed,
  count(d.email) filter (where d.status in ('pending', 'sending'))::int as remaining,
  coalesce((array_agg(d.email || ': ' || d.error order by d.email) filter (where d.error is not null))[1:20], '{}') as errors
from public.campaigns c
left join public.deliveries d on d.campaign_id = c.id
group by c.id;

-- Queue a send to everyone on the list.
create function public.start_campaign(p_subject text, p_body text, p_track jsonb, p_sent_by text, p_mode text)
returns uuid
language plpgsql
set search_path = ''
as $$
declare
  v_id uuid;
begin
  if not exists (select 1 from public.subscribers) then
    raise exception 'Nobody has signed up yet.';
  end if;
  if exists (select 1 from public.campaigns where status = 'sending') then
    raise exception 'Another email is still sending. Wait for it to finish.';
  end if;
  insert into public.campaigns (subject, body, track, sent_by, mode)
  values (p_subject, p_body, p_track, p_sent_by, p_mode)
  returning id into v_id;
  insert into public.deliveries (campaign_id, email)
  select v_id, email from public.subscribers;
  return v_id;
end;
$$;

-- Take the next batch of recipients to send to. Rows another request claimed
-- but never finished (it timed out) are retried after 3 minutes. People who
-- unsubscribed since the send started are skipped.
create function public.claim_deliveries(p_campaign uuid, p_limit integer)
returns setof public.deliveries
language plpgsql
set search_path = ''
as $$
begin
  update public.deliveries d
  set status = 'skipped', updated_at = now()
  where d.campaign_id = p_campaign
    and d.status = 'pending'
    and not exists (select 1 from public.subscribers s where s.email = d.email);

  return query
  update public.deliveries d
  set status = 'sending', updated_at = now()
  where (d.campaign_id, d.email) in (
    select x.campaign_id, x.email
    from public.deliveries x
    where x.campaign_id = p_campaign
      and (x.status = 'pending' or (x.status = 'sending' and x.updated_at < now() - interval '3 minutes'))
    order by x.email
    limit p_limit
    for update skip locked
  )
  returning d.*;
end;
$$;

-- Mark the send finished once nobody is left to send to.
create function public.finish_campaign(p_campaign uuid)
returns void
language sql
set search_path = ''
as $$
  update public.campaigns c
  set status = case
        when exists (select 1 from public.deliveries d where d.campaign_id = c.id and d.status = 'sent') then 'sent'
        else 'failed'
      end,
      finished_at = now()
  where c.id = p_campaign
    and c.status = 'sending'
    and not exists (
      select 1 from public.deliveries d
      where d.campaign_id = c.id and d.status in ('pending', 'sending')
    );
$$;

-- Only the server (secret key) may see the summary or call the functions.
revoke all on public.campaign_summary from anon, authenticated;
revoke execute on function public.start_campaign(text, text, jsonb, text, text) from public, anon, authenticated;
revoke execute on function public.claim_deliveries(uuid, integer) from public, anon, authenticated;
revoke execute on function public.finish_campaign(uuid) from public, anon, authenticated;
grant execute on function public.start_campaign(text, text, jsonb, text, text) to service_role;
grant execute on function public.claim_deliveries(uuid, integer) to service_role;
grant execute on function public.finish_campaign(uuid) to service_role;

-- ---------- media bucket ----------

-- Public to read (cover art and audio are on the public site). Uploads only
-- happen through one-time signed URLs the server hands to signed-in admins.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'media', 'media', true, 62914560,
  array['image/jpeg', 'image/png', 'image/webp', 'audio/mpeg', 'audio/mp4', 'audio/x-m4a', 'audio/wav', 'audio/x-wav', 'audio/wave']
)
on conflict (id) do nothing;
