import json
import subprocess
from unittest.mock import patch

from .exiftool import extract_lens, run_exiftool


def _completed(stdout, returncode=0):
    return subprocess.CompletedProcess(
        args=['exiftool'], returncode=returncode, stdout=stdout, stderr=b''
    )


def test_returns_first_object_without_source_file():
    payload = json.dumps([{'SourceFile': '-', 'Make': 'NIKON', 'FNumber': 2.8}])
    with patch('subprocess.run', return_value=_completed(payload.encode())) as run:
        result = run_exiftool(b'image-bytes')
    assert result == {'Make': 'NIKON', 'FNumber': 2.8}
    args, kwargs = run.call_args
    assert args[0][0] == 'exiftool'
    assert kwargs['input'] == b'image-bytes'


def test_returns_empty_dict_when_binary_missing():
    with patch('subprocess.run', side_effect=FileNotFoundError):
        assert run_exiftool(b'data') == {}


def test_returns_empty_dict_on_nonzero_exit():
    with patch('subprocess.run', return_value=_completed(b'', returncode=1)):
        assert run_exiftool(b'data') == {}


def test_returns_empty_dict_on_invalid_json():
    with patch('subprocess.run', return_value=_completed(b'not json')):
        assert run_exiftool(b'data') == {}


def test_returns_empty_dict_on_empty_list():
    with patch('subprocess.run', return_value=_completed(b'[]')):
        assert run_exiftool(b'data') == {}


def test_returns_empty_dict_on_timeout():
    with patch(
        'subprocess.run',
        side_effect=subprocess.TimeoutExpired(cmd='exiftool', timeout=30),
    ):
        assert run_exiftool(b'data') == {}


def test_extract_lens_uses_printconv_without_numeric_flag():
    # '-n' would disable the Nikon LensID lookup, returning raw hex bytes
    # instead of the decoded lens name, so the lens call must not use it.
    payload = json.dumps([{'LensID': 'NIKKOR Z 24-70mm f/2.8 S'}])
    with patch('subprocess.run', return_value=_completed(payload.encode())) as run:
        result = extract_lens(b'image-bytes')
    assert result == {'LensID': 'NIKKOR Z 24-70mm f/2.8 S'}
    command = run.call_args[0][0]
    assert '-n' not in command
    assert '-LensID' in command


def test_extract_lens_returns_empty_dict_when_binary_missing():
    with patch('subprocess.run', side_effect=FileNotFoundError):
        assert extract_lens(b'data') == {}
