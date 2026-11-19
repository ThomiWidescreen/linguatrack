"""First acquisition is a trust-on-first-download snapshot, never an upstream checksum claim."""
import os
import tempfile
import urllib.request
from pathlib import Path
from .core import digest, canonical, validate_lock


def snapshot(args, catalog, languages):
    source = catalog[args.source]
    # Explicit URL allowlist per audited source; acquisition does not change review status.
    if not any(args.url.startswith(prefix) for prefix in source.get('download_prefixes', [])):
        raise ValueError('URL is outside the reviewed source download prefixes')
    item = dict(source=args.source, language=args.language, format=args.format,
                path=args.file, url=args.url, revision=args.revision, sha256='0'*64)
    if args.compression:
        item['compression'] = args.compression
    validate_lock({'version':1,'inputs':[item]}, catalog, languages)
    lock = Path(args.lock)
    target = Path(args.file)
    if lock.exists() or target.exists():
        raise ValueError('Snapshot target and lock must be new paths')
    target.parent.mkdir(parents=True, exist_ok=True)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as out, urllib.request.urlopen(args.url,timeout=120) as response:
            if not response.url.startswith('https://'):
                raise ValueError('Insecure redirect')
            while chunk := response.read(1024*1024):
                out.write(chunk)
        item['sha256'] = digest(temp)
        item['path'] = os.path.relpath(target.resolve(), lock.parent.resolve())
        # These are observed bytes, not publisher-signed or publisher-verified bytes.
        result = {'version':1, 'acquisition':'observed-https-sha256', 'inputs':[item]}
        os.replace(temp,target)
        lock.write_text(canonical(result)+'\n',encoding='utf-8')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
