# Design

Source for the "Seaside Guitarist UI" design canvas:
https://claude.ai/artifact/ApHp4eAAY2VBEBtvHWnq5f

## Layout

- `project/canvas.json` — canvas index: which artboards exist and where they sit.
- `project/Main.dc.html` — website home page (fluid, 1360px wide on the canvas).
- `project/Music.dc.html`, `Tour.dc.html`, `About.dc.html`, `Subscribe.dc.html` — one page per
  nav link, each a copy of that landing-page section under a short photo banner.
- `project/Player.dc.html` — phone "porch session" player (390×844).
- `assets/` — images the artboards use.
- `tools/grade.py` — the crop, colour grade and film grain applied to the photo.

## Assets

The artboards reference uploaded images by canvas URL, not by file name:

| URL in the code | File |
| --- | --- |
| `/_blob/19ef719a2ab77ff6ff2d87fdd8cdc308` | `assets/ocean-fence-grain.jpg` |
| `/_blob/dd151d96f2525bfea0d503fe1697f045` | `assets/grain-tile.png` |
| `/_blob/5d76ac8ee81df8f4f6d4b2c62316bef6` | `assets/hero-polaroid.jpg` |
| `/_blob/39a2399fa062a7c144d533a0e704597d` | `assets/cover-1.jpg` |
| `/_blob/33185b2b6d0aa75a0089cb7058632c03` | `assets/cover-2.jpg` |
| `/_blob/1fc3fd50e67ee11266189695ab46b67e` | `assets/cover-3.jpg` |
| `/_blob/9134c877ffdc3cfa9dc6e97b489b4b32` | `assets/cover-4.jpg` |

Those URLs only resolve inside the canvas, and the `.dc.html` files load
`./support.js`, which the canvas provides. The local server (`server/app.py`)
handles both: it renders the pages itself and maps each URL to its file using
`assets/manifest.json`. Add a line there for every new image uploaded to the
canvas.

`assets/ocean-fence-original.jpg` is the unprocessed photo. To regenerate the
graded version (needs Pillow and NumPy):

```sh
python3 design/tools/grade.py design/assets/ocean-fence-original.jpg design/assets
```

The landing section uses `assets/ocean-fence-hero.jpg`, the same photo with
the grain at 0.45 strength (pass the strength as a third argument). It is not
on the canvas, so the home page points at it by file path (`/assets/...`),
which only the local server resolves.

The second, third and fourth song covers (`assets/cover-2-palms.jpg`,
`cover-3-shore.jpg`, `cover-4-guitar.jpg`) are also loaded by file path and are
not on the canvas yet.

That also writes a `preview.jpg`, and it does not reproduce one manual step:
the blue sign on the right was desaturated afterwards.

## Photo credit

Seaside Park beach, New Jersey, by Wikimedia Commons user Dough4872 (2008).
Released into the public domain by the author.
https://commons.wikimedia.org/wiki/File:Seaside_Park_beach_south_of_Funtown_Pier.JPG
