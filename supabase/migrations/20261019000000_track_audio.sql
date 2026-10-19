-- Songs play on the page. `audio` is an uploaded file the site's own player
-- streams; there's no download link. `link` is now an optional streaming link
-- (Spotify, Apple Music…), and can be empty when a track only plays on the site.

alter table public.tracks add column audio text not null default '';
alter table public.tracks alter column link_label set default 'Stream';

-- Audio uploaded before this was saved as the track's link, which the site
-- showed as a download. Move it to `audio` so it plays on the page instead.
update public.tracks
set audio = link, link = ''
where link ~* '/storage/v1/object/public/media/[^/?#]+\.(mp3|m4a|wav)$';

update public.tracks set link_label = 'Stream' where link_label = 'Stream / Download';
