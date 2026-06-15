"""Interactive Wikidata tagger: write qids/<stem>.json sidecars for a photo.

Q-IDs are the one thing Darktable can't store (IPTC Extension linked-data
fields don't survive its export round-trip), so they live in sidecars next to
the master. This opens the photo, searches Wikidata as you type, and on each
selection appends the Q-ID to the sidecar and seeds wikidata_cache.json so the
build stays offline.

    $ uv run tag.py content/albums/2026-japan/web/DSC0042.jpg
    Tagging DSC0042.jpg
    search> schloonsee
      [0]  Q2239936  Schloonsee — lake in Germany
      number + kind (a=about, p=place, l=person)> 0 a
      ✓ wrote about: Q2239936 (Schloonsee)
    search>                       # empty line = done
"""

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from build import enrich, load_cache, save_cache

_API = 'https://www.wikidata.org/w/api.php'
_USER_AGENT = 'picura-static/0.0 (tagging helper)'
# Relation keys match the qids sidecar / IPTC Extension model.
_KINDS = {'a': 'about', 'p': 'place', 'l': 'person'}


def _search(term, lang='en', limit=7):
    params = urllib.parse.urlencode({
        'action': 'wbsearchentities',
        'format': 'json',
        'language': lang,
        'uselang': lang,
        'search': term,
        'limit': limit,
    })
    request = urllib.request.Request(
        f'{_API}?{params}', headers={'User-Agent': _USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response).get('search', [])


def _open_in_viewer(path):
    opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
    try:
        subprocess.Popen(
            [opener, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass  # headless / no viewer — tagging still works without the preview


def _sidecar_path(photo):
    # web/<stem>.jpg  ->  qids/<stem>.json  (siblings under the album dir)
    return photo.parent.parent / 'qids' / f'{photo.stem}.json'


def _load_sidecar(path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {}


def _save_sidecar(path, sidecar):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def _parse_choice(text, results):
    """Parse a ``<index> <kind>`` reply into ``(qid, relation)`` or ``None``."""
    parts = text.split()
    if len(parts) != 2:
        return None
    index, kind = parts
    if kind not in _KINDS or not index.isdigit():
        return None
    index = int(index)
    if not 0 <= index < len(results):
        return None
    return results[index]['id'], _KINDS[kind]


def tag_photo(photo, cache_path='wikidata_cache.json', lang='en'):
    photo = Path(photo)
    sidecar_path = _sidecar_path(photo)
    sidecar = _load_sidecar(sidecar_path)
    cache = load_cache(cache_path)

    print(f'Tagging {photo.name}')
    _open_in_viewer(photo)

    try:
        while True:
            term = input('search> ').strip()
            if not term:
                break
            results = _search(term, lang)
            if not results:
                print('  (no matches)')
                continue
            for i, result in enumerate(results):
                desc = result.get('description', '')
                suffix = f' — {desc}' if desc else ''
                print(f'  [{i}]  {result["id"]}  {result.get("label", "")}{suffix}')
            selection = _parse_choice(input('  number + kind (a=about, p=place, l=person)> '), results)
            if selection is None:
                print('  (skipped)')
                continue
            qid, relation = selection
            ids = sidecar.setdefault(relation, [])
            if qid not in ids:
                ids.append(qid)
            entity = enrich(qid, cache)  # seeds the cache
            labels = entity['labels']
            label = labels.get(lang) or labels.get('en') or labels.get('de') or qid
            print(f'  ✓ wrote {relation}: {qid} ({label})')
    except (EOFError, KeyboardInterrupt):
        print()

    _save_sidecar(sidecar_path, sidecar)
    save_cache(cache_path, cache)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Tag a photo with Wikidata Q-IDs.')
    parser.add_argument('photo', type=Path, help='path to a web/<name>.jpg export')
    parser.add_argument('--cache', default='wikidata_cache.json',
                        help='Wikidata label/coord cache to seed')
    parser.add_argument('--lang', default='en', help='search/display language')
    parser.add_argument('--clear', action='store_true',
                        help="delete the photo's sidecar and exit")
    args = parser.parse_args(argv)

    if args.clear:
        path = _sidecar_path(args.photo)
        if path.exists():
            path.unlink()
            print(f'Removed {path}')
        else:
            print('No sidecar to remove')
        return

    tag_photo(args.photo, cache_path=args.cache, lang=args.lang)


if __name__ == '__main__':
    main()
