"""Bounded-memory SQLite staging and deterministic JSONL exports."""
import json
import platform
import shutil
import sqlite3
import tempfile
from pathlib import Path
from . import __version__
from .adapters import ADAPTERS
from .core import TABLES, canonical, digest, identifier, validate_lock, read_json


def build(lock_path, catalog_path, languages_path, output, distribution=False, allow_nc=False):
    lock_path = Path(lock_path)
    lock, catalog, languages = map(read_json, (lock_path, catalog_path, languages_path))
    validate_lock(lock, catalog, languages, distribution, allow_nc)
    output = Path(output)
    if output.exists():
        raise ValueError('Output exists; select a fresh directory')
    # Verify ALL bytes before parsing or producing artifacts.
    for item in lock['inputs']:
        path = lock_path.parent / item['path']
        if digest(path) != item['sha256']:
            raise ValueError('Checksum mismatch: ' + item['source'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp)
        db = sqlite3.connect(stage / 'stage.sqlite')
        db.execute('CREATE TABLE records(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))')
        counts = {}
        try:
            for item in sorted(lock['inputs'], key=lambda i: i['source']):
                source = catalog[item['source']]
                for kind, data in ADAPTERS[item['format']](item, lock_path.parent / item['path']):
                    locator = data.pop('locator')
                    # Every assertion carries its own origin, license and source locator.
                    data['provenance'] = {'source': item['source'], 'revision': item['revision'],
                        'sha256': item['sha256'], 'locator': locator, 'license': source['license'],
                        'url': item['url'], 'confidence': 0.9, 'confidence_basis': 'import_fidelity_heuristic'}
                    data['schema_version'] = '1.0'
                    data['id'] = identifier(kind, data)
                    db.execute('INSERT OR IGNORE INTO records VALUES (?,?,?)', (kind, data['id'], canonical(data)))
                db.commit()
            # Check internal references before exporting.
            entries = db.execute("SELECT body FROM records WHERE kind='entries'")
            db.execute('CREATE TABLE entry_ids(id TEXT PRIMARY KEY)')
            for (body,) in entries:
                db.execute('INSERT OR IGNORE INTO entry_ids VALUES (?)', (json.loads(body)['entry_id'],))
            for (body,) in db.execute("SELECT body FROM records WHERE kind IN ('forms','senses','morphology','relations')"):
                if not db.execute('SELECT 1 FROM entry_ids WHERE id=?', (json.loads(body)['entry_id'],)).fetchone():
                    raise ValueError('Dangling entry reference')
            for kind in TABLES:
                n = 0
                with (stage / (kind + '.jsonl')).open('w', encoding='utf-8', newline='\n') as out:
                    for (body,) in db.execute('SELECT body FROM records WHERE kind=? ORDER BY id', (kind,)):
                        out.write(body + '\n')
                        n += 1
                counts[kind] = n
        finally:
            db.close()
        (stage / 'stage.sqlite').unlink()
        sources = {i['source']: catalog[i['source']] for i in lock['inputs']}
        manifest = {'pipeline_version': __version__, 'python': platform.python_version(),
            'lock': lock, 'catalog_sha256': digest(catalog_path), 'languages_sha256': digest(languages_path),
            'sources': sources, 'distribution_checked': distribution, 'counts': counts,
            'files': {k + '.jsonl': digest(stage / (k + '.jsonl')) for k in TABLES}}
        (stage / 'manifest.json').write_text(canonical(manifest) + '\n', encoding='utf-8')
        notices = ['# Attribution and data terms', '', 'Modified by LinguaTrack: normalized into schema 1.0.', '']
        for sid, source in sorted(sources.items()):
            notices += [f"## {sid}", source['attribution'], 'License: ' + source['license'],
                        *source['evidence'], source.get('notes', ''), '']
        (stage / 'ATTRIBUTION.md').write_text('\n'.join(notices), encoding='utf-8')
        # Publish the completed directory only after success.
        shutil.move(str(stage), str(output))
    return manifest
