import argparse
import json
import shutil
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from extraction import extract_image_metadata

_TEMPLATES = Path(__file__).parent / 'templates'
_STATIC = Path(__file__).parent / 'static'

_WIKIDATA_API = 'https://www.wikidata.org/w/api.php'
_USER_AGENT = 'picura-static/0.0 (static photo portfolio build)'
_LABEL_LANGS = ('de', 'en')

# Map a site.yaml format name to its Pillow save format and the file
# extension used in output filenames (which templates reference verbatim,
# e.g. ``{{ photo.stem }}-display.jpeg``).
_FORMATS = {
    'jpeg': ('JPEG', 'jpeg'),
    'webp': ('WEBP', 'webp'),
    'avif': ('AVIF', 'avif'),
}


def _target_size(width, height, target_width):
    # Never upscale: Darktable already exports the display size, so a source
    # narrower than the target keeps its dimensions.
    if width <= target_width:
        return width, height
    return target_width, round(height * target_width / width)


def plan_variants(stem, size, images_config):
    """Compute the variant filenames and dimensions ``fan_out`` would produce.

    Pure metadata, no image work — lets the build decide whether the outputs
    are already up to date before paying to re-encode them.
    """
    formats = images_config['formats']  # {fmt: {'quality': n}}
    sizes = {k: v for k, v in images_config.items() if k != 'formats'}
    width, height = size
    variants = {}
    for size_name, spec in sizes.items():
        w, h = _target_size(width, height, spec['width'])
        variants[size_name] = {
            'width': w,
            'height': h,
            'sources': {
                fmt: f'{stem}-{size_name}.{_FORMATS[fmt][1]}' for fmt in formats
            },
        }
    return variants


def fan_out(src, out_dir, images_config):
    """Generate resized derivatives of ``src`` in every configured format.

    ``images_config`` is the ``images:`` block from site.yaml: a ``formats``
    mapping (each format to its ``quality``) plus one entry per size
    (``thumb``, ``display``, ...) with a ``width``. Returns a mapping of size
    name to its pixel dimensions and the per-format output filenames, ready
    for templating.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = images_config['formats']
    sizes = {k: v for k, v in images_config.items() if k != 'formats'}

    with Image.open(src) as img:
        img.load()
        base = img.convert('RGB')
        # Preserve the embedded ICC profile (Darktable writes sRGB) so the
        # derivatives stay color-managed.
        icc = img.info.get('icc_profile')
        variants = plan_variants(src.stem, base.size, images_config)

        for size_name, spec in sizes.items():
            w, h = _target_size(base.width, base.height, spec['width'])
            resized = base if (w, h) == base.size else base.resize((w, h), Image.LANCZOS)
            for fmt, filename in variants[size_name]['sources'].items():
                pil_format = _FORMATS[fmt][0]
                save_kwargs = {'quality': formats[fmt]['quality']}
                if icc:
                    save_kwargs['icc_profile'] = icc
                resized.save(out_dir / filename, pil_format, **save_kwargs)
    return variants


def _env():
    return Environment(
        loader=FileSystemLoader(_TEMPLATES),
        autoescape=select_autoescape(['html']),
    )


def _find_cover(photos, cover):
    if cover:
        stem = Path(cover).stem
        for photo in photos:
            if photo['stem'] == stem:
                return photo
    return photos[0] if photos else None


def render(site, albums, out_dir):
    """Write the index page and one page per album into ``out_dir``.

    ``albums`` is a list of ``{'slug', 'meta', 'photos'}`` where ``meta`` is
    the parsed album.yaml and each photo carries a ``stem``, ``caption``,
    ``alt`` and the ``variants`` mapping from :func:`fan_out`. Unlisted albums
    are built but kept off the index. Variant filenames are relative, so each
    album page lives alongside its own derivative images.
    """
    out_dir = Path(out_dir)
    env = _env()

    cards = []
    for album in albums:
        meta = album['meta']
        cards.append({
            'slug': album['slug'],
            'title': meta.get('title', album['slug']),
            'date': meta.get('date'),
            'description': meta.get('description'),
            'cover': _find_cover(album['photos'], meta.get('cover')),
            'unlisted': meta.get('unlisted', False),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    listed = [card for card in cards if not card['unlisted']]
    # ``root`` is the relative path back to the site root, so shared assets
    # (style.css) resolve from pages at any depth.
    (out_dir / 'index.html').write_text(
        env.get_template('index.html').render(site=site, albums=listed, root=''),
        encoding='utf-8',
    )

    for album, card in zip(albums, cards):
        album_dir = out_dir / 'albums' / album['slug']
        album_dir.mkdir(parents=True, exist_ok=True)
        (album_dir / 'index.html').write_text(
            env.get_template('album.html').render(
                site=site, album=card, photos=album['photos'], root='../../'
            ),
            encoding='utf-8',
        )


def _outputs_current(src, out_dir, variants):
    # Up to date only if every derivative exists and is at least as new as the
    # source export — the incremental check that keeps rebuilds cheap.
    src_mtime = src.stat().st_mtime
    for variant in variants.values():
        for filename in variant['sources'].values():
            out = out_dir / filename
            if not out.exists() or out.stat().st_mtime < src_mtime:
                return False
    return True


def _caption(meta, stem, m):
    # Precedence: album.yaml override -> embedded title -> embedded
    # description -> none.
    overrides = meta.get('captions') or {}
    for key in (stem, f'{stem}.jpg'):
        if key in overrides:
            return overrides[key]
    return m['title'] or m['description'] or None


# --- Wikidata authority data --------------------------------------------
#
# Q-IDs live in qids/<stem>.json sidecars next to the master (they don't
# survive a Darktable export). Enrichment is offline-first: labels/coords are
# read from wikidata_cache.json and the API is hit only on a cache miss, so
# repeat builds are fast and work with no network.


def load_qids(path):
    """Read a ``{relation: [qid, ...]}`` sidecar, or ``{}`` if it's absent."""
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def load_cache(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def save_cache(path, cache):
    Path(path).write_text(
        json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def _coordinate(claims):
    for claim in claims.get('P625', []):
        try:
            value = claim['mainsnak']['datavalue']['value']
        except (KeyError, TypeError):
            continue
        return value['latitude'], value['longitude']
    return None


def _fetch_entity(qid):
    """Fetch de/en labels and coordinates for ``qid`` from the Wikidata API."""
    params = urllib.parse.urlencode({
        'action': 'wbgetentities',
        'format': 'json',
        'ids': qid,
        'props': 'labels|claims',
        'languages': '|'.join(_LABEL_LANGS),
    })
    request = urllib.request.Request(
        f'{_WIKIDATA_API}?{params}', headers={'User-Agent': _USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    entity = data['entities'][qid]
    raw_labels = entity.get('labels', {})
    result = {
        'labels': {
            lang: raw_labels[lang]['value']
            for lang in _LABEL_LANGS
            if lang in raw_labels
        }
    }
    coord = _coordinate(entity.get('claims', {}))
    if coord:
        result['lat'], result['lon'] = coord
    return result


def enrich(qid, cache):
    """Return cached entity data for ``qid``, fetching + caching on a miss.

    A failed fetch is not cached, so the next build retries it; it yields an
    empty-label stub so the build never breaks on a network hiccup.
    """
    if qid not in cache:
        # One ``except`` per type: ruff format mangles multi-type tuples
        # (see extraction/exiftool.py).
        try:
            cache[qid] = _fetch_entity(qid)
        except OSError:
            return {'qid': qid, 'labels': {}}
        except ValueError:
            return {'qid': qid, 'labels': {}}
        except KeyError:
            return {'qid': qid, 'labels': {}}
    return {'qid': qid, **cache[qid]}


def _entities(qids, cache):
    entities = []
    for relation, ids in qids.items():
        for qid in ids:
            entity = enrich(qid, cache)
            labels = entity['labels']
            entities.append({
                **entity,
                'relation': relation,
                'label': labels.get('en') or labels.get('de') or qid,
            })
    return entities


def build_album(site, album_dir, out_root, cache):
    """Extract, fan out (incrementally), and assemble one album's photos."""
    meta = yaml.safe_load((album_dir / 'album.yaml').read_text())
    slug = album_dir.name
    album_out = out_root / 'albums' / slug
    qids_dir = album_dir / 'qids'

    photos = []
    for jpg in sorted((album_dir / 'web').glob('*.jpg')):
        with jpg.open('rb') as f:
            m = extract_image_metadata(f)
        with Image.open(jpg) as img:
            variants = plan_variants(jpg.stem, img.size, site['images'])
        if not _outputs_current(jpg, album_out, variants):
            fan_out(jpg, album_out, site['images'])
        caption = _caption(meta, jpg.stem, m)
        entities = _entities(load_qids(qids_dir / f'{jpg.stem}.json'), cache)
        photos.append({
            'stem': jpg.stem,
            'caption': caption,
            'alt': caption or jpg.stem,
            'title': m['title'],
            'description': m['description'],
            'taken_at': m['taken_at'],
            'camera_model': m['camera_model'],
            'lens': m['lens'],
            'keywords': m['keywords'],
            'entities': entities,
            'variants': variants,
        })
    return {'slug': slug, 'meta': meta, 'photos': photos}


def _order_albums(site, albums):
    # site.yaml album_order wins; anything unlisted there falls back to
    # date-descending.
    by_slug = {album['slug']: album for album in albums}
    ordered = []
    for slug in site.get('album_order') or []:
        if slug in by_slug:
            ordered.append(by_slug.pop(slug))
    rest = sorted(
        by_slug.values(),
        key=lambda a: a['meta'].get('date') or date.min,
        reverse=True,
    )
    return ordered + rest


def build(content_dir='content', out_dir='dist', site_path='site.yaml',
          cache_path='wikidata_cache.json'):
    """Build the whole site: every album under ``content_dir`` into ``out_dir``."""
    out_dir = Path(out_dir)
    site = yaml.safe_load(Path(site_path).read_text())
    cache = load_cache(cache_path)
    albums_dir = Path(content_dir) / 'albums'
    album_dirs = sorted(
        d for d in albums_dir.iterdir() if (d / 'album.yaml').exists()
    )
    albums = [build_album(site, d, out_dir, cache) for d in album_dirs]
    albums = _order_albums(site, albums)
    render(site, albums, out_dir)
    _copy_static(out_dir)
    save_cache(cache_path, cache)
    return albums


def _copy_static(out_dir):
    if not _STATIC.is_dir():
        return
    for asset in _STATIC.iterdir():
        if asset.is_file():
            shutil.copy2(asset, out_dir / asset.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the static photo site.')
    parser.add_argument('--content', default='content', help='content directory')
    parser.add_argument('--out', default='dist', help='build output directory')
    parser.add_argument('--site', default='site.yaml', help='site config file')
    parser.add_argument('--cache', default='wikidata_cache.json',
                        help='Wikidata label/coord cache')
    args = parser.parse_args(argv)
    albums = build(content_dir=args.content, out_dir=args.out,
                   site_path=args.site, cache_path=args.cache)
    total = sum(len(album['photos']) for album in albums)
    print(f'Built {len(albums)} album(s), {total} photo(s) → {args.out}')


if __name__ == '__main__':
    main()
