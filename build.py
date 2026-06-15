from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

_TEMPLATES = Path(__file__).parent / 'templates'

# Map a site.yaml format name to its Pillow save format and the file
# extension used in output filenames (which templates reference verbatim,
# e.g. ``{{ photo.stem }}-display.jpeg``).
_FORMATS = {
    'jpeg': ('JPEG', 'jpeg'),
    'webp': ('WEBP', 'webp'),
    'avif': ('AVIF', 'avif'),
}


def _resize_to_width(img, target_width):
    # Never upscale: Darktable already exports the display size, so a source
    # narrower than the target is used as-is.
    if img.width <= target_width:
        return img.copy()
    height = round(img.height * target_width / img.width)
    return img.resize((target_width, height), Image.LANCZOS)


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
    formats = images_config['formats']
    sizes = {k: v for k, v in images_config.items() if k != 'formats'}

    variants = {}
    with Image.open(src) as img:
        img.load()
        base = img.convert('RGB')
        # Preserve the embedded ICC profile (Darktable writes sRGB) so the
        # derivatives stay color-managed.
        icc = img.info.get('icc_profile')

        for size_name, spec in sizes.items():
            resized = _resize_to_width(base, spec['width'])
            sources = {}
            for fmt in formats:
                pil_format, ext = _FORMATS[fmt]
                filename = f'{src.stem}-{size_name}.{ext}'
                save_kwargs = {'quality': spec['quality']}
                if icc:
                    save_kwargs['icc_profile'] = icc
                resized.save(out_dir / filename, pil_format, **save_kwargs)
                sources[fmt] = filename
            variants[size_name] = {
                'width': resized.width,
                'height': resized.height,
                'sources': sources,
            }
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
