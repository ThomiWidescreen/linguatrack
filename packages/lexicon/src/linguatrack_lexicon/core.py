"""Stable identifiers, strict input locks and conservative license policy."""
import gzip
import hashlib
import json
import re
import unicodedata
from pathlib import Path

TABLES = ('entries', 'forms', 'senses', 'morphology', 'relations', 'frequency', 'cefr')
UPOS = set('ADJ ADP ADV AUX CCONJ DET INTJ NOUN NUM PART PRON PROPN PUNCT SCONJ SYM VERB X'.split())
POS = dict(adjective='ADJ', adverb='ADV', preposition='ADP', conjunction='CCONJ', interjection='INTJ', numeral='NUM', pronoun='PRON', determiner='DET', noun='NOUN', verb='VERB', adj='ADJ', adv='ADV', name='PROPN', pron='PRON',
           det='DET', prep='ADP', conj='CCONJ', intj='INTJ', num='NUM', particle='PART')

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def identifier(*parts):
    return hashlib.sha256(canonical(parts).encode()).hexdigest()

def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Expected non-empty text')
    return unicodedata.normalize('NFC', value.strip())

def upos(value):
    return value if value in UPOS else POS.get(value, 'X')

def open_text(path, compression=None):
    return gzip.open(path, 'rt', encoding='utf-8') if compression == 'gzip' else Path(path).open(encoding='utf-8')

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def validate_lock(lock, catalog, languages, distribution=False, allow_nc=False):
    if lock.get('version') != 1 or not lock.get('inputs'):
        raise ValueError('Expected version 1 lock with inputs')
    seen = set()
    for item in lock['inputs']:
        source = catalog[item['source']]
        input_key = (item['source'], item['language'], item['path'], item['format'])
        if input_key in seen:
            raise ValueError('Duplicate source; combine shards under separate audited source IDs')
        seen.add(input_key)
        if source['status'] != 'approved':
            raise ValueError('Source is quarantined: ' + item['source'])
        if distribution and not source['redistribute']:
            raise ValueError('Redistribution not approved: ' + item['source'])
        if source.get('noncommercial') and not allow_nc:
            raise ValueError('NC data requires --allow-nc and a separate build')
        if not source.get('evidence') or not source.get('attribution'):
            raise ValueError('Missing license evidence/attribution')
        if item['language'] not in languages or item['language'] not in source['languages']:
            raise ValueError('Unsupported source/language combination')
        if item['format'] not in source.get('formats', []):
            raise ValueError('Unapproved format')
        if not re.fullmatch('[0-9a-f]{64}', item.get('sha256', '')) or not item.get('revision'):
            raise ValueError('Input must have SHA-256 and revision')
        if item.get('compression') not in (None, 'gzip'):
            raise ValueError('Unsupported compression')
        if not item.get('url', '').startswith('https://') and not item.get('synthetic'):
            raise ValueError('Expected upstream HTTPS URL')
    if distribution:
        sa = {catalog[i['source']]['license'] for i in lock['inputs'] if 'SA-' in catalog[i['source']]['license']}
        if len(sa) > 1:
            raise ValueError('Different share-alike licenses require separate distribution builds')
    # Keep NC and unrestricted share-alike data in separate artifacts.
    nc = {bool(catalog[i['source']].get('noncommercial')) for i in lock['inputs']}
    if len(nc) > 1:
        raise ValueError('Mixed NC/open builds are not supported')
