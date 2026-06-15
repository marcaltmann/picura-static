import argparse
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from extraction import extract_image_metadata

_TEMPLATES = Path(__file__).parent / 'templates'

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
    formats = images_config['formats']
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
    list plus one entry per size (``thumb``, ``display``, ...), each with a
    ``width`` and ``quality``. Returns a mapping of size name to its pixel
    dimensions and the per-format output filenames, ready for templating.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
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
                save_kwargs = {'quality': spec['quality']}
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
    (out_dir / 'index.html').write_text(
        env.get_template('index.html').render(site=site, albums=listed),
        encoding='utf-8',
    )

    for album, card in zip(albums, cards):
        album_dir = out_dir / 'albums' / album['slug']
        album_dir.mkdir(parents=True, exist_ok=True)
        (album_dir / 'index.html').write_text(
            env.get_template('album.html').render(
                site=site, album=card, photos=album['photos']
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


def build_album(site, album_dir, out_root):
    """Extract, fan out (incrementally), and assemble one album's photos."""
    meta = yaml.safe_load((album_dir / 'album.yaml').read_text())
    slug = album_dir.name
    album_out = out_root / 'albums' / slug

    photos = []
    for jpg in sorted((album_dir / 'web').glob('*.jpg')):
        with jpg.open('rb') as f:
            m = extract_image_metadata(f)
        with Image.open(jpg) as img:
            variants = plan_variants(jpg.stem, img.size, site['images'])
        if not _outputs_current(jpg, album_out, variants):
            fan_out(jpg, album_out, site['images'])
        caption = _caption(meta, jpg.stem, m)
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


def build(content_dir='content', out_dir='dist', site_path='site.yaml'):
    """Build the whole site: every album under ``content_dir`` into ``out_dir``."""
    out_dir = Path(out_dir)
    site = yaml.safe_load(Path(site_path).read_text())
    albums_dir = Path(content_dir) / 'albums'
    album_dirs = sorted(
        d for d in albums_dir.iterdir() if (d / 'album.yaml').exists()
    )
    albums = [build_album(site, d, out_dir) for d in album_dirs]
    albums = _order_albums(site, albums)
    render(site, albums, out_dir)
    return albums


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the static photo site.')
    parser.add_argument('--content', default='content', help='content directory')
    parser.add_argument('--out', default='dist', help='build output directory')
    parser.add_argument('--site', default='site.yaml', help='site config file')
    args = parser.parse_args(argv)
    albums = build(content_dir=args.content, out_dir=args.out, site_path=args.site)
    total = sum(len(album['photos']) for album in albums)
    print(f'Built {len(albums)} album(s), {total} photo(s) → {args.out}')


if __name__ == '__main__':
    main()
