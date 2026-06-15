import os

import yaml
from PIL import Image

from build import build, fan_out, render

_IMAGES = {
    'thumb': {'width': 600, 'quality': 80},
    'display': {'width': 2000, 'quality': 82},
    'formats': ['avif', 'webp', 'jpeg'],
}


def _source(tmp_path, size=(2000, 1336)):
    path = tmp_path / 'DSC0042.jpg'
    Image.new('RGB', size, color='red').save(path, 'JPEG')
    return path


def test_emits_every_size_and_format(tmp_path):
    out = tmp_path / 'out'
    variants = fan_out(_source(tmp_path), out, _IMAGES)

    assert set(variants) == {'thumb', 'display'}
    for size_name in ('thumb', 'display'):
        sources = variants[size_name]['sources']
        assert set(sources) == {'avif', 'webp', 'jpeg'}
        for fmt, filename in sources.items():
            assert filename == f'DSC0042-{size_name}.{fmt}'
            assert (out / filename).exists()


def test_thumb_is_scaled_to_target_width_keeping_aspect(tmp_path):
    variants = fan_out(_source(tmp_path, size=(2000, 1000)), tmp_path / 'out', _IMAGES)
    assert variants['thumb']['width'] == 600
    assert variants['thumb']['height'] == 300


def test_does_not_upscale_below_target_width(tmp_path):
    variants = fan_out(_source(tmp_path, size=(800, 600)), tmp_path / 'out', _IMAGES)
    assert variants['display']['width'] == 800
    assert variants['display']['height'] == 600


def test_output_files_are_decodable_in_their_format(tmp_path):
    out = tmp_path / 'out'
    fan_out(_source(tmp_path), out, _IMAGES)
    with Image.open(out / 'DSC0042-thumb.avif') as img:
        assert img.format == 'AVIF'
        assert img.width == 600
    with Image.open(out / 'DSC0042-display.webp') as img:
        assert img.format == 'WEBP'


_SITE = {'title': 'Marc Altmann — Photography'}


def _photo(stem='DSC0042', caption='Schloonsee'):
    variant = lambda size: {
        'width': 600 if size == 'thumb' else 2000,
        'height': 401 if size == 'thumb' else 1336,
        'sources': {fmt: f'{stem}-{size}.{fmt}' for fmt in ('avif', 'webp', 'jpeg')},
    }
    return {
        'stem': stem,
        'caption': caption,
        'alt': caption,
        'variants': {'thumb': variant('thumb'), 'display': variant('display')},
    }


def _album(slug='2026-japan', cover='DSC0042.jpg', unlisted=False):
    return {
        'slug': slug,
        'meta': {'title': slug.title(), 'cover': cover, 'unlisted': unlisted},
        'photos': [_photo()],
    }


def test_render_writes_index_and_album_pages(tmp_path):
    render(_SITE, [_album()], tmp_path)
    assert (tmp_path / 'index.html').exists()
    assert (tmp_path / 'albums' / '2026-japan' / 'index.html').exists()


def test_index_links_albums_with_cover_thumb(tmp_path):
    render(_SITE, [_album()], tmp_path)
    index = (tmp_path / 'index.html').read_text()
    assert 'href="albums/2026-japan/"' in index
    assert 'albums/2026-japan/DSC0042-thumb.avif' in index


def test_album_page_emits_responsive_picture(tmp_path):
    render(_SITE, [_album()], tmp_path)
    page = (tmp_path / 'albums' / '2026-japan' / 'index.html').read_text()
    assert 'srcset="DSC0042-display.avif" type="image/avif"' in page
    assert 'src="DSC0042-display.jpeg"' in page
    assert '<figcaption>Schloonsee</figcaption>' in page


def test_unlisted_album_built_but_off_index(tmp_path):
    render(_SITE, [_album(unlisted=True)], tmp_path)
    index = (tmp_path / 'index.html').read_text()
    assert 'albums/2026-japan/' not in index
    assert (tmp_path / 'albums' / '2026-japan' / 'index.html').exists()


def _content_tree(tmp_path, album='2026-japan', extra_album_yaml=''):
    web = tmp_path / 'content' / 'albums' / album / 'web'
    web.mkdir(parents=True)
    Image.new('RGB', (2000, 1336), color='blue').save(web / 'DSC0042.jpg', 'JPEG')
    (web.parent / 'album.yaml').write_text(
        f'title: Japan 2026\ndate: 2026-04-12\ncover: DSC0042.jpg\n{extra_album_yaml}'
    )
    site = tmp_path / 'site.yaml'
    site.write_text(yaml.safe_dump({
        'title': 'Test', 'album_order': [album], 'images': _IMAGES,
    }))
    return site


def test_build_writes_full_site(tmp_path):
    site = _content_tree(tmp_path)
    out = tmp_path / 'dist'
    build(content_dir=tmp_path / 'content', out_dir=out, site_path=site)

    assert (out / 'index.html').exists()
    album_out = out / 'albums' / '2026-japan'
    assert (album_out / 'index.html').exists()
    assert (album_out / 'DSC0042-display.avif').exists()
    assert (album_out / 'DSC0042-thumb.webp').exists()


def test_album_yaml_caption_overrides_embedded(tmp_path):
    site = _content_tree(tmp_path, extra_album_yaml='captions:\n  DSC0042.jpg: Forced Title\n')
    out = tmp_path / 'dist'
    build(content_dir=tmp_path / 'content', out_dir=out, site_path=site)
    page = (out / 'albums' / '2026-japan' / 'index.html').read_text()
    assert '<figcaption>Forced Title</figcaption>' in page


def test_incremental_skips_unchanged_photos(tmp_path):
    site = _content_tree(tmp_path)
    out = tmp_path / 'dist'
    build(content_dir=tmp_path / 'content', out_dir=out, site_path=site)

    source = tmp_path / 'content' / 'albums' / '2026-japan' / 'web' / 'DSC0042.jpg'
    variant = out / 'albums' / '2026-japan' / 'DSC0042-display.avif'
    # Source older than its derivatives; stamp the output with a marker mtime.
    os.utime(source, (1_000_000, 1_000_000))
    os.utime(variant, (2_000_000, 2_000_000))

    build(content_dir=tmp_path / 'content', out_dir=out, site_path=site)
    assert variant.stat().st_mtime == 2_000_000  # untouched = skipped


def test_incremental_rebuilds_when_source_is_newer(tmp_path):
    site = _content_tree(tmp_path)
    out = tmp_path / 'dist'
    build(content_dir=tmp_path / 'content', out_dir=out, site_path=site)

    source = tmp_path / 'content' / 'albums' / '2026-japan' / 'web' / 'DSC0042.jpg'
    variant = out / 'albums' / '2026-japan' / 'DSC0042-display.avif'
    # Source newer than its derivatives -> must regenerate.
    os.utime(variant, (1_000_000, 1_000_000))
    os.utime(source, (2_000_000, 2_000_000))

    build(content_dir=tmp_path / 'content', out_dir=out, site_path=site)
    assert variant.stat().st_mtime != 1_000_000  # rewritten
