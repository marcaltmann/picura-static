from PIL import Image

from build import fan_out

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
