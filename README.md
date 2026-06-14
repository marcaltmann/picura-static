# picura-static — concept

A possible rebuild of [Picura](../picura) as a **static site generator** for a personal,
fully-public photo portfolio. This document is a concept sketch — **nothing is built yet.**

## The idea

Drop the server, database, and auth entirely. The "backoffice" becomes
**Darktable + a text editor + one build script**. Photos are processed and organized in
Darktable, exported as web JPEGs, enriched with a little metadata, built into static HTML +
resized images, and deployed to GitHub Pages.

### Accepted caveats

- Everything is **public**; every album is treated the same.
- No per-user accounts, no private/unlisted albums, no server-side features (upload-from-phone,
  search, comments).

For a personal public portfolio this is a feature, not a loss — the simplicity is the point.

## The core tension

Photos are **big binaries**; git/GitHub is for **small text**. Keep three things separate:

1. **Originals** — full-res RAW masters. Live in the Darktable library, *never* in this repo.
2. **Source-of-truth metadata** — captions, tags, geotags (in Darktable), album info + Q-IDs
   (in this repo as text). Tiny.
3. **Build output** — generated HTML + *web-sized* derivative images. This is what gets deployed.

## End-to-end loop

```
┌─ DARKTABLE (backoffice) ──────────────────────────────────┐
│ 1. Cull + edit (ratings, color labels)                    │
│ 2. Caption: title/description in metadata editor          │
│ 3. Geotag in map view                                     │
│ 4. Curate: tag chosen photos  album:japan-2026  (≥3★)     │
│ 5. Export preset "picura-web" → content/albums/.../web/   │
└───────────────────────────────────────────────────────────┘
            │ web JPEGs (captions, GPS, keywords embedded)
            ▼
┌─ tag.py (occasional) ─────────────────────────────────────┐
│ Search Wikidata, write qids/DSC0042.json + seed cache     │
└───────────────────────────────────────────────────────────┘
            │
            ▼
┌─ build.py ────────────────────────────────────────────────┐
│ a. read embedded metadata   (extraction/  ← reused)       │
│ b. merge Q-ID sidecars + wikidata_cache (de/en labels)    │
│ c. fan out small variants   (thumb + webp/avif)           │
│ d. render templates → dist/                               │
└───────────────────────────────────────────────────────────┘
            │
            ▼
┌─ deploy ──────────────────────────────────────────────────┐
│ force-push dist/ → orphan gh-pages branch (GitHub Pages)  │
└───────────────────────────────────────────────────────────┘
```

## Folder layout

```
picura-static/
  site.yaml                      # global config
  build.py                       # the build script
  extraction/                    # lifted from Picura, de-Django'd
    __init__.py
    exiftool.py
  tag.py                         # Wikidata helper → writes sidecars
  templates/
    index.html
    album.html
  content/
    albums/
      2026-japan/
        album.yaml               # album-level info only (title, date, cover)
        web/                     # ← Darktable export target (gitignored)
          DSC0042.jpg            #   2000px sRGB, metadata embedded
        qids/                    # ← tag.py sidecars (committed)
          DSC0042.json           #   {"about":["Q1187927"],"place":["Q34600"]}
  wikidata_cache.json            # labels/coords, committed (build reads offline)
  dist/                          # build output, deployed (gitignored)
```

RAWs + Darktable XMP sidecars stay in the Darktable library, never in this repo. Only the
exported web JPEGs (gitignored) and the tiny text (album.yaml, qids, cache) live here.

## Darktable: the backoffice

Darktable is both the editing tool and the derivative generator. A lot of metadata flows into
the site **for free** because Picura's existing extractor already reads exactly what Darktable
writes on export:

| In Darktable you...               | Writes                  | Extractor reads        |
|-----------------------------------|-------------------------|------------------------|
| Add tags/keywords                 | `Xmp.dc.subject`        | `keywords`             |
| Fill title / description          | IPTC/XMP                | `title`, `description` |
| Geotag (map view, GPX tracks)     | `GPSLatitude/Longitude` | `latitude`, `longitude`|
| Set copyright / creator           | IPTC                    | `copyright`, `creator` |

### Curation = provenance/curation split, in a tool already used

- **Provenance** = film rolls (= `_originals` folders, one per shoot).
- **Curation** = a tag like `album:japan-2026` + a star threshold ("published = tagged + ≥3★").

Album membership/ordering then comes from a Darktable collection query, not a hand-maintained
YAML list.

### Export preset "picura-web"

```
Storage:   file on disk
Path:       content/albums/$(TAG:album)/web/$(FILE_NAME)
Format:     JPEG, quality 82
Size:       2000 px (max dimension)
Profile:    sRGB
Intent:     output sharpening on
Metadata:   keep — tags, title/description, GPS, copyright
```

The `$(TAG:album)` variable routes each photo to the right album folder, so curation and
foldering happen in one export action. Darktable's output (proper color management + output
sharpening) is a better "display" image than a naive Pillow thumbnail.

## Metadata schemas

### `content/site.yaml`

```yaml
title: Marc Altmann — Photography
base_url: https://photos.example.com
author: Marc Altmann
album_order: [2026-japan, 2025-garden]   # or fall back to date-descending

images:
  thumb:   { width: 600,  quality: 80 }
  display: { width: 2000, quality: 82 }   # (Darktable already does this size)
  formats: [avif, webp, jpeg]
```

### `content/albums/2026-japan/album.yaml`

Album-level info only — captions come from embedded metadata, membership from Darktable.

```yaml
title: Japan 2026
date: 2026-04-12
description: Two weeks, mostly Kyoto and Tokyo.
cover: DSC0042.jpg
unlisted: false        # if true: built, but not on the index page
```

Caption precedence at build time: `album.yaml` override (if present) → embedded
`Description`/`Title` → none.

## Authority data (Wikidata Q-IDs / Normdaten)

The one thing Darktable can't do. IPTC Extension has purpose-built fields for linked data:

| Depicts          | IPTC structure            | ID field                     |
|------------------|---------------------------|------------------------------|
| Subject/topic    | `AboutCvTerms`            | `CvTermId` = entity URI      |
| Place shown      | `LocationShown`           | `LocationId` (list of URIs)  |
| Person shown     | `PersonInImageWDetails`   | `PersonId` (list of URIs)    |
| Artwork/object   | `ArtworkOrObject`         | `AOCreatorId`, etc.          |

**Important:** these IPTC Ext fields **do not survive a Darktable export round-trip** (Darktable
doesn't model them). So store Q-IDs in **sidecars next to the master**, not in the image:

```
qids/DSC0042.json  →  {"about": ["Q1187927"], "place": ["Q34600"]}
```

The build merges sidecars with embedded metadata.

### What the Q-IDs buy you

- **Multilingual labels for free** — store `Q4176` once, fetch `de`/`en` labels at build time
  (feeds the existing i18n: "Kölner Dom" / "Cologne Cathedral").
- **Auto-enrichment** — coordinates, "instance of", inception date, Wikipedia/Commons links.
- **Canonical faceted browsing** — "Köln"/"Cologne"/"Cologne, Germany" collapse to Q365.
- **Maps** — coordinates from place entities.
- **schema.org JSON-LD** with `sameAs` → SEO + machine-readable.
- **Wikimedia Commons interop** — same model (`depicts P180 = Q-ID`); photos arrive pre-tagged.

### `tag.py` — Wikidata helper (stdlib + exiftool, ~100 lines)

Opens the photo in the OS viewer, searches Wikidata (`wbsearchentities`), and on selection
writes a sidecar + seeds `wikidata_cache.json`. Using it:

```
$ uv run tag.py content/albums/2026-japan/web/DSC0042.jpg
Tagging DSC0042.jpg               # ← photo opens in image viewer
search> arashiyama bamboo
  [0]   Q1187927  Arashiyama Bamboo Grove — tourist attraction in Kyoto
  number + kind (a/p/l)> 0 a
  ✓ wrote about: Q1187927 (Arashiyama Bamboo Grove)
search>                            # empty line = done
```

Refinements when needed: `--clear` to fix a tag; a batch mode to apply one tag across a glob
(highest-value extension); a small local FastAPI page if the terminal flow gets annoying.

## `build.py` — ~120 lines of glue

Darktable already did resize + metadata, so the script is mostly assembly:

```python
def build_album(site, album_dir):
    meta = yaml.safe_load((album_dir / 'album.yaml').read_text())
    photos = []
    for jpg in sorted((album_dir / 'web').glob('*.jpg')):
        with jpg.open('rb') as f:
            m = extract_image_metadata(f)          # captions, GPS, keywords — free
        qids = load_qids(album_dir / 'qids' / f'{jpg.stem}.json')
        m['entities'] = [enrich(q) for q in qids]  # labels[de/en] + coords, cached
        m['variants'] = fan_out(jpg)               # thumb + webp/avif via Pillow
        photos.append(m)
    render(meta, photos)
```

`enrich(qid)` reads `wikidata_cache.json` first, hits Wikidata only on a miss, writes back —
fully offline and fast after the first run.

Templates emit responsive `<picture>`:

```html
<picture>
  <source srcset="{{ photo.stem }}-display.avif" type="image/avif">
  <source srcset="{{ photo.stem }}-display.webp" type="image/webp">
  <img src="{{ photo.stem }}-display.jpeg" alt="{{ photo.caption }}" loading="lazy">
</picture>
```

## Reusing `extraction/` from Picura

The single most fiddly part of Picura — EXIF quirks, ICC profiles, EXIF rotation, lens-database
lookup, IPTC/XMP fallbacks — is already a clean unit, almost framework-free:

- `extraction/exiftool.py` — **zero Django**. Lifts over verbatim (incl. the LensID
  print-conversion pass and stdin-based invocation).
- `extraction/__init__.py` — **one** Django dependency: `django.utils.timezone` in
  `_parse_taken_at`. Swap `timezone.make_aware(naive)` for stdlib tz handling and it's portable.

> Note: it calls exiftool once per image, twice (archive + lens pass). Fine one-at-a-time; for
> batch builds, exiftool `-stay_open` daemon mode (or `pyexiftool`) avoids hundreds of process
> spawns. Don't bother until builds feel slow — the incremental `mtime` check means you only pay
> it for new photos.

## Deploy: GitHub Pages

Simplest possible deploy; fine for a personal portfolio. Two things to design in from the start:

1. **Don't bloat repo history with image binaries.** Git keeps every version forever. Publish to
   a **force-pushed orphan `gh-pages` branch from a local build** (single throwaway commit, no
   history) — e.g. `git push --force origin HEAD:gh-pages`, or `peaceiris/actions-gh-pages`.
   Keep `dist/` gitignored on `master`; master stays text-only.

2. **Image budget.** Pages soft limits: site < 1 GB, ~100 GB/month bandwidth. At 2000px AVIF
   (~250–400 KB/photo) that's ~2,500–4,000 photos before nearing the 1 GB cap. AVIF/WebP isn't
   just speed — it's headroom. Drop display to 1600px if it gets tight.

3. **Free escape hatch, no rebuild.** Put **Cloudflare (free)** in front for edge caching (the
   bandwidth limit stops mattering) + CDN. Because the build separates HTML from images, moving
   just the image bytes to R2 later is a URL-prefix change, not a redesign. "Pages now" doesn't
   lock out "R2 later."

## Off-the-shelf alternative

Before building a custom engine: **Hugo** has a strong build-time image pipeline (resize/convert/
responsive `srcset`) and galleries are a common use case; **Eleventy** + the image plugin is the
JS equivalent. Either gets ~80% of "Picura static" off the shelf — the real work becomes the
metadata format and gallery layout, not the engine. A custom Python SSG is justified mainly by
reusing the `extraction/` + Wikidata work and keeping everything in one language.

## Status & first step

**Concept only — not started.** When picked up, **slice-zero** is de-Django'ing the `extraction/`
module into a standalone copy (swap the single `timezone` call), giving a working, framework-free
metadata reader to build outward from.
