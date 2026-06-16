import json
import os
from unittest.mock import patch

import yaml
from PIL import Image

from build import build, enrich, fan_out, load_qids, render

_IMAGES = {
    'thumb': {'width': 600},
    'display': {'width': 2000},
    'formats': {
        'avif': {'quality': 60},
        'webp': {'quality': 80},
        'jpeg': {'quality': 82},
    },
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
    assert '>Schloonsee</figcaption>' in page


def test_unlisted_album_built_but_off_index(tmp_path):
    render(_SITE, [_album(unlisted=True)], tmp_path)
    index = (tmp_path / 'index.html').read_text()
    assert 'albums/2026-japan/' not in index
    assert (tmp_path / 'albums' / '2026-japan' / 'index.html').exists()


def _content_tree(tmp_path, album='2026-japan', extra_album_yaml='', qids=None, cname=None):
    web = tmp_path / 'content' / 'albums' / album / 'web'
    web.mkdir(parents=True)
    Image.new('RGB', (2000, 1336), color='blue').save(web / 'DSC0042.jpg', 'JPEG')
    (web.parent / 'album.yaml').write_text(
        f'title: Japan 2026\ndate: 2026-04-12\ncover: DSC0042.jpg\n{extra_album_yaml}'
    )
    if qids is not None:
        qids_dir = web.parent / 'qids'
        qids_dir.mkdir()
        (qids_dir / 'DSC0042.json').write_text(json.dumps(qids))
    config = {'title': 'Test', 'album_order': [album], 'images': _IMAGES}
    if cname is not None:
        config['cname'] = cname
    site = tmp_path / 'site.yaml'
    site.write_text(yaml.safe_dump(config))
    return site


def _build(tmp_path, site, **kw):
    return build(
        content_dir=tmp_path / 'content',
        out_dir=tmp_path / 'dist',
        site_path=site,
        cache_path=tmp_path / 'cache.json',
        **kw,
    )


def test_build_writes_full_site(tmp_path):
    _build(tmp_path, _content_tree(tmp_path))
    out = tmp_path / 'dist'

    assert (out / 'index.html').exists()
    album_out = out / 'albums' / '2026-japan'
    assert (album_out / 'index.html').exists()
    assert (album_out / 'DSC0042-display.avif').exists()
    assert (album_out / 'DSC0042-thumb.webp').exists()
    assert (out / 'style.css').exists()


def test_cname_written_when_configured(tmp_path):
    _build(tmp_path, _content_tree(tmp_path, cname='photos.marcaltmann.com'))
    cname = tmp_path / 'dist' / 'CNAME'
    assert cname.read_text() == 'photos.marcaltmann.com\n'


def test_no_cname_without_config(tmp_path):
    _build(tmp_path, _content_tree(tmp_path))
    assert not (tmp_path / 'dist' / 'CNAME').exists()


def test_album_yaml_caption_overrides_embedded(tmp_path):
    site = _content_tree(tmp_path, extra_album_yaml='captions:\n  DSC0042.jpg: Forced Title\n')
    _build(tmp_path, site)
    page = (tmp_path / 'dist' / 'albums' / '2026-japan' / 'index.html').read_text()
    assert '>Forced Title</figcaption>' in page


def test_incremental_skips_unchanged_photos(tmp_path):
    site = _content_tree(tmp_path)
    _build(tmp_path, site)

    source = tmp_path / 'content' / 'albums' / '2026-japan' / 'web' / 'DSC0042.jpg'
    variant = tmp_path / 'dist' / 'albums' / '2026-japan' / 'DSC0042-display.avif'
    # Source older than its derivatives; stamp the output with a marker mtime.
    os.utime(source, (1_000_000, 1_000_000))
    os.utime(variant, (2_000_000, 2_000_000))

    _build(tmp_path, site)
    assert variant.stat().st_mtime == 2_000_000  # untouched = skipped


def test_incremental_rebuilds_when_source_is_newer(tmp_path):
    site = _content_tree(tmp_path)
    _build(tmp_path, site)

    source = tmp_path / 'content' / 'albums' / '2026-japan' / 'web' / 'DSC0042.jpg'
    variant = tmp_path / 'dist' / 'albums' / '2026-japan' / 'DSC0042-display.avif'
    # Source newer than its derivatives -> must regenerate.
    os.utime(variant, (1_000_000, 1_000_000))
    os.utime(source, (2_000_000, 2_000_000))

    _build(tmp_path, site)
    assert variant.stat().st_mtime != 1_000_000  # rewritten


def test_load_qids_missing_returns_empty(tmp_path):
    assert load_qids(tmp_path / 'nope.json') == {}


def test_enrich_uses_cache_without_fetching():
    cache = {'Q1': {'labels': {'en': 'One'}}}
    with patch('build._fetch_entity', side_effect=AssertionError('must not fetch')):
        entity = enrich('Q1', cache)
    assert entity == {'qid': 'Q1', 'labels': {'en': 'One'}}


def test_enrich_fetches_and_caches_on_miss():
    cache = {}
    fetched = {'labels': {'en': 'Grove'}, 'lat': 35.0, 'lon': 135.7}
    with patch('build._fetch_entity', return_value=fetched) as fetch:
        entity = enrich('Q1187927', cache)
    assert entity == {'qid': 'Q1187927', **fetched}
    assert cache['Q1187927'] == fetched
    # Cached now: a second call must not hit the network.
    with patch('build._fetch_entity', side_effect=AssertionError('must not fetch')):
        enrich('Q1187927', cache)


def test_enrich_network_error_does_not_cache():
    cache = {}
    with patch('build._fetch_entity', side_effect=OSError('offline')):
        entity = enrich('Q1', cache)
    assert entity == {'qid': 'Q1', 'labels': {}}
    assert cache == {}  # failure not cached, so next build retries


def test_build_renders_wikidata_entity_tags(tmp_path):
    site = _content_tree(tmp_path, qids={'about': ['Q1187927']})
    with patch('build._fetch_entity',
               return_value={'labels': {'en': 'Arashiyama Bamboo Grove'}}):
        _build(tmp_path, site)
    page = (tmp_path / 'dist' / 'albums' / '2026-japan' / 'index.html').read_text()
    assert 'https://www.wikidata.org/wiki/Q1187927' in page
    assert 'Arashiyama Bamboo Grove' in page


def test_build_writes_cache_back(tmp_path):
    site = _content_tree(tmp_path, qids={'about': ['Q1187927']})
    with patch('build._fetch_entity', return_value={'labels': {'en': 'Grove'}}):
        _build(tmp_path, site)
    cache = json.loads((tmp_path / 'cache.json').read_text())
    assert cache['Q1187927']['labels']['en'] == 'Grove'
