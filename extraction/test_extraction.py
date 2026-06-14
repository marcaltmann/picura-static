import io
from unittest.mock import patch

from PIL import Image

from . import extract_image_metadata


def _image_file(size=(640, 480), mode='RGB'):
    img = Image.new(mode, size, color='red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    return buf


def _extract(raw, file=None, lens=None):
    file = file or _image_file()
    with (
        patch('extraction.run_exiftool', return_value=raw),
        patch('extraction.extract_lens', return_value=lens or {}),
    ):
        return extract_image_metadata(file)


def test_reads_dimensions_and_format_from_pillow():
    result = _extract({}, file=_image_file(size=(800, 600)))
    assert result['width'] == 800
    assert result['height'] == 600
    assert result['format'] == 'JPEG'
    assert result['color_mode'] == 'RGB'


def test_unreadable_file_yields_all_none():
    file = io.BytesIO(b'not a real image')
    result = _extract({}, file=file)
    assert result['width'] is None
    assert result['height'] is None
    assert result['camera_make'] is None
    assert result['raw'] == {}


def test_stores_full_raw_archive():
    raw = {'Make': 'NIKON', 'CustomTag': 'whatever'}
    result = _extract(raw)
    assert result['raw'] == raw


def test_maps_camera_fields():
    result = _extract({'Make': 'NIKON', 'Model': 'NIKON Z 9'})
    assert result['camera_make'] == 'NIKON'
    assert result['camera_model'] == 'NIKON Z 9'


def test_lens_prefers_decoded_lens_id():
    lens = {'LensID': 'NIKKOR Z 24-70mm f/2.8 S', 'LensModel': 'fallback'}
    assert _extract({}, lens=lens)['lens'] == 'NIKKOR Z 24-70mm f/2.8 S'


def test_lens_falls_back_to_lens_model():
    lens = {'LensModel': 'EF 50mm f/1.4 USM'}
    assert _extract({}, lens=lens)['lens'] == 'EF 50mm f/1.4 USM'


def test_lens_is_none_without_lens_call_result():
    assert _extract({'LensID': 'B2 00 5C 80 30 30 B4 0E'})['lens'] is None


def test_maps_exposure_fields_as_floats():
    raw = {'FNumber': 2.8, 'ExposureTime': 0.004, 'FocalLength': 35.0, 'ISO': 400}
    result = _extract(raw)
    assert result['aperture'] == 2.8
    assert result['exposure_time'] == 0.004
    assert result['focal_length'] == 35.0
    assert result['iso'] == 400


def test_derives_shutter_speed_from_exposure_time():
    assert _extract({'ExposureTime': 0.004})['shutter_speed'] == '1/250'
    assert _extract({'ExposureTime': 2.0})['shutter_speed'] == '2'


def test_shutter_speed_none_without_exposure_time():
    assert _extract({})['shutter_speed'] is None


def test_maps_gps_coordinates():
    result = _extract({'GPSLatitude': -33.85, 'GPSLongitude': -70.66})
    assert result['latitude'] == -33.85
    assert result['longitude'] == -70.66


def test_parses_taken_at_as_aware_datetime():
    result = _extract({'DateTimeOriginal': '2024:06:15 10:30:00'})
    assert result['taken_at'] is not None
    assert result['taken_at'].tzinfo is not None
    assert result['taken_at'].replace(tzinfo=None).isoformat() == '2024-06-15T10:30:00'


def test_invalid_taken_at_is_none():
    assert _extract({'DateTimeOriginal': 'garbage'})['taken_at'] is None


def test_maps_descriptive_fields():
    raw = {
        'Title': 'Sunset',
        'Description': 'A lake at dusk',
        'Keywords': ['lake', 'dusk'],
        'Copyright': '© Marc',
        'Creator': 'Marc Altmann',
    }
    result = _extract(raw)
    assert result['title'] == 'Sunset'
    assert result['description'] == 'A lake at dusk'
    assert result['keywords'] == ['lake', 'dusk']
    assert result['copyright'] == '© Marc'
    assert result['creator'] == 'Marc Altmann'


def test_single_keyword_normalized_to_list():
    assert _extract({'Keywords': 'solo'})['keywords'] == ['solo']


def test_missing_descriptive_fields_default_empty():
    result = _extract({})
    assert result['title'] is None
    assert result['description'] is None
    assert result['keywords'] == []
    assert result['copyright'] is None
    assert result['creator'] is None
