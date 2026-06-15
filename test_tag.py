import json
from unittest.mock import patch

import tag


def _photo(tmp_path, name='DSC0042.jpg'):
    web = tmp_path / 'content' / 'albums' / '2026-japan' / 'web'
    web.mkdir(parents=True)
    photo = web / name
    photo.write_bytes(b'')  # viewer is mocked; contents don't matter
    return photo


_RESULTS = [
    {'id': 'Q2239936', 'label': 'Schloonsee', 'description': 'lake in Germany'},
    {'id': 'Q545', 'label': 'Baltic Sea', 'description': 'marginal sea'},
]


def test_sidecar_path_is_qids_sibling_of_web(tmp_path):
    photo = _photo(tmp_path)
    assert tag._sidecar_path(photo) == photo.parent.parent / 'qids' / 'DSC0042.json'


def test_parse_choice_valid():
    assert tag._parse_choice('0 a', _RESULTS) == ('Q2239936', 'about')
    assert tag._parse_choice('1 p', _RESULTS) == ('Q545', 'place')


def test_parse_choice_rejects_bad_input():
    assert tag._parse_choice('', _RESULTS) is None
    assert tag._parse_choice('0', _RESULTS) is None
    assert tag._parse_choice('0 x', _RESULTS) is None       # unknown kind
    assert tag._parse_choice('9 a', _RESULTS) is None        # out of range
    assert tag._parse_choice('a a', _RESULTS) is None        # non-numeric index


def _run(photo, cache_path, inputs):
    with (
        patch('tag._open_in_viewer'),
        patch('tag._search', return_value=_RESULTS),
        patch('tag.enrich', return_value={'qid': 'Q2239936', 'labels': {'en': 'Schloonsee'}}),
        patch('builtins.input', side_effect=inputs),
    ):
        tag.tag_photo(photo, cache_path=cache_path)


def test_tag_photo_writes_sidecar(tmp_path):
    photo = _photo(tmp_path)
    cache_path = tmp_path / 'cache.json'
    # search, pick result 0 as 'about', then empty line to finish.
    _run(photo, cache_path, ['schloonsee', '0 a', ''])

    sidecar = json.loads(tag._sidecar_path(photo).read_text())
    assert sidecar == {'about': ['Q2239936']}


def test_tag_photo_does_not_duplicate_existing_qid(tmp_path):
    photo = _photo(tmp_path)
    sidecar_path = tag._sidecar_path(photo)
    sidecar_path.parent.mkdir(parents=True)
    sidecar_path.write_text(json.dumps({'about': ['Q2239936']}))

    _run(photo, tmp_path / 'cache.json', ['schloonsee', '0 a', ''])
    assert json.loads(sidecar_path.read_text()) == {'about': ['Q2239936']}


def test_clear_removes_sidecar(tmp_path):
    photo = _photo(tmp_path)
    sidecar_path = tag._sidecar_path(photo)
    sidecar_path.parent.mkdir(parents=True)
    sidecar_path.write_text('{}')

    tag.main([str(photo), '--clear'])
    assert not sidecar_path.exists()
