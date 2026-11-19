import argparse
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from .build import build
from .core import read_json, validate_lock, digest, canonical
from .acquire import snapshot


def fetch(lock_path, catalog_path, languages_path, allow_nc=False):
    lock_path = Path(lock_path)
    lock = read_json(lock_path)
    validate_lock(lock, read_json(catalog_path), read_json(languages_path), allow_nc=allow_nc)
    for item in lock['inputs']:
        path = lock_path.parent / item['path']
        if path.exists():
            if digest(path) != item['sha256']:
                raise ValueError('Existing file checksum mismatch: ' + str(path))
            continue
        if item.get('synthetic'):
            raise ValueError('Synthetic fixture missing; restore it from git')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(item['url'], timeout=120) as response:
                if not response.url.startswith('https://'):
                    raise ValueError('Insecure redirect')
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if digest(temp) != item['sha256']:
                raise ValueError('Downloaded file checksum mismatch: ' + item['source'])
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


def main():
    p = argparse.ArgumentParser(description='Build provenance-preserving lexical dictionaries')
    p.add_argument('--catalog', default='catalog/sources.json')
    p.add_argument('--languages', default='catalog/languages.json')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('fetch', 'build'):
        s = sub.add_parser(name)
        s.add_argument('--lock', required=True)
        s.add_argument('--allow-nc', action='store_true')
        if name == 'build':
            s.add_argument('--out', required=True)
            s.add_argument('--distribution', action='store_true')
    snap = sub.add_parser('snapshot', help='Acquire reviewed source bytes and create a SHA-256 lock')
    for field in ('source', 'language', 'format', 'url', 'revision', 'file', 'lock'):
        snap.add_argument('--' + field, required=True)
    snap.add_argument('--compression', choices=['gzip'])
    sub.add_parser('audit')
    a = p.parse_args()
    try:
        if a.command == 'audit':
            print(json.dumps(read_json(a.catalog), ensure_ascii=False, indent=2))
        elif a.command == 'snapshot':
            snapshot(a, read_json(a.catalog), read_json(a.languages))
        elif a.command == 'fetch':
            fetch(a.lock, a.catalog, a.languages, a.allow_nc)
        else:
            result = build(a.lock, a.catalog, a.languages, a.out, a.distribution, a.allow_nc)
            print(json.dumps(result['counts'], sort_keys=True))
    except (ValueError, KeyError, OSError) as error:
        p.exit(1, f'Error: {error}\n')

if __name__ == '__main__':
    main()
