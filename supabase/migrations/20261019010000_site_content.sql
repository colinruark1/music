-- Copy the admin edits for the site's shared sections (hero, shows, about,
-- subscribe, links, footer): one row per section, as JSON. A section with no
-- row keeps the design's own text. See server/content.py.

create table public.site_content (
  section text primary key,
  value jsonb not null,
  updated_by text,
  updated_at timestamptz not null default now()
);

alter table public.site_content enable row level security;
