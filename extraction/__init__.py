import io
from datetime import datetime
from fractions import Fraction
from zoneinfo import ZoneInfo

from PIL import Image, ImageCms

from .exiftool import extract_lens, run_exiftool

# EXIF DateTimeOriginal carries no time zone; assume photos were taken in this
# one. Change it to wherever you shoot. (In Picura this was Django's
# settings.TIME_ZONE via timezone.make_aware.)
LOCAL_TIMEZONE = ZoneInfo('Europe/Berlin')


def _extract_icc_profile(img):
    icc_data = img.info.get('icc_profile')
    if not icc_data:
        return None
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_data))
        return ImageCms.getProfileName(profile).strip()
    except Exception:
        return None


def _str_or_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_str(*values):
    for value in values:
        text = _str_or_none(value)
        if text is not None:
            return text
    return None


def _float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
    except TypeError:
        return None


def _int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
    except TypeError:
        return None


def _parse_taken_at(value):
    if not value:
        return None
    try:
        naive = datetime.strptime(str(value), '%Y:%m:%d %H:%M:%S')
    except ValueError:
        return None
    return naive.replace(tzinfo=LOCAL_TIMEZONE)


def _shutter_speed(exposure_time):
    if exposure_time is None:
        return None
    frac = Fraction(exposure_time).limit_denominator(100000)
    if frac.denominator == 1:
        return str(frac.numerator)
    return f'{frac.numerator}/{frac.denominator}'


def _keywords(raw):
    value = raw.get('Keywords')
    if value is None:
        value = raw.get('Subject')
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result = []
    for item in items:
        text = _str_or_none(item)
        if text is not None:
            result.append(text)
    return result


def _empty_result():
    return {
        'title': None,
        'description': None,
        'width': None,
        'height': None,
        'format': None,
        'color_mode': None,
        'icc_profile': None,
        'taken_at': None,
        'camera_make': None,
        'camera_model': None,
        'lens': None,
        'aperture': None,
        'exposure_time': None,
        'shutter_speed': None,
        'focal_length': None,
        'iso': None,
        'latitude': None,
        'longitude': None,
        'keywords': [],
        'copyright': None,
        'creator': None,
        'raw': {},
    }


def extract_image_metadata(file):
    result = _empty_result()
    try:
        data = file.read()
    except Exception:
        return result
    finally:
        try:
            file.seek(0)
        except Exception:
            pass

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return result

    result['width'], result['height'] = img.size
    result['format'] = img.format
    result['color_mode'] = img.mode
    result['icc_profile'] = _extract_icc_profile(img)

    raw = run_exiftool(data)
    result['raw'] = raw
    result['taken_at'] = _parse_taken_at(raw.get('DateTimeOriginal'))
    result['camera_make'] = _str_or_none(raw.get('Make'))
    result['camera_model'] = _str_or_none(raw.get('Model'))
    lens = extract_lens(data)
    result['lens'] = _first_str(
        lens.get('LensID'), lens.get('LensModel'), lens.get('Lens')
    )
    result['aperture'] = _float_or_none(raw.get('FNumber'))
    result['exposure_time'] = _float_or_none(raw.get('ExposureTime'))
    result['shutter_speed'] = _shutter_speed(result['exposure_time'])
    result['focal_length'] = _float_or_none(raw.get('FocalLength'))
    result['iso'] = _int_or_none(raw.get('ISO'))
    result['latitude'] = _float_or_none(raw.get('GPSLatitude'))
    result['longitude'] = _float_or_none(raw.get('GPSLongitude'))
    result['title'] = _first_str(
        raw.get('Title'), raw.get('ObjectName'), raw.get('Headline')
    )
    result['description'] = _first_str(
        raw.get('Description'),
        raw.get('Caption-Abstract'),
        raw.get('ImageDescription'),
    )
    result['keywords'] = _keywords(raw)
    result['copyright'] = _first_str(raw.get('Copyright'), raw.get('Rights'))
    result['creator'] = _first_str(
        raw.get('Creator'), raw.get('By-line'), raw.get('Artist')
    )
    return result
