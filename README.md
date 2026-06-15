# picura-static

A static site generator for a personal, fully-public photo portfolio.

Photos are edited and exported in Darktable; this tool reads their embedded
metadata (captions, keywords, GPS, EXIF), generates responsive AVIF/WebP/JPEG
derivatives, enriches them with Wikidata authority data, renders static HTML,
and publishes the result to GitHub Pages. No server, database, or auth.

The build keeps three things separate: **originals** stay in the Darktable
library (never in this repo), **source-of-truth metadata** lives in the photos
and small text sidecars, and the **build output** (`dist/`) is generated and
deployed. See [`STATIC_SITE.md`](STATIC_SITE.md) for the full design rationale.

## Setup

```sh
uv sync
```

Requires [`exiftool`](https://exiftool.org/) on your `PATH` for metadata
extraction.

## Usage

**1. Add photos.** Export web-sized JPEGs from Darktable into an album's
`web/` folder (gitignored), with metadata kept on export:

```
content/albums/2026-japan/web/DSC0042.jpg
```

Album-level info lives in `content/albums/2026-japan/album.yaml`; global config
in `site.yaml`.

**2. Tag with Wikidata (optional).** Q-IDs add multilingual labels, coordinates,
and linked data. The interactive tagger writes a `qids/` sidecar and seeds the
offline cache:

```sh
uv run tag.py content/albums/2026-japan/web/DSC0042.jpg
```

At `search>` type a term; at the prompt type `<index> <kind>` (`a`=about,
`p`=place, `l`=person), e.g. `0 a`. Empty line finishes. `--clear` removes a
sidecar; `--lang de` switches language.

**3. Build.**

```sh
uv run python build.py
```

Reads metadata → generates image variants → enriches Q-IDs (offline via
`wikidata_cache.json`) → renders `dist/`. Rebuilds only changed photos.
Flags: `--content`, `--out`, `--site`, `--cache`.

**4. Preview.**

```sh
uv run python -m http.server 8000 --directory dist
# open http://localhost:8000/
```

**5. Deploy.** Publishes `dist/` to the `gh-pages` branch as a single
force-pushed commit (keeps `main` text-only). Needs a git remote and Pages set
to serve from `gh-pages`:

```sh
./deploy.sh
```

## Tests

```sh
uv run python -m pytest -q
```
