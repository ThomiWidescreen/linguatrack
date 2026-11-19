"""Streaming adapters. Input line locators survive every transformation."""
import csv
import json
from urllib.parse import quote
from .core import open_text, text, upos, identifier

RELATIONS = ('synonyms', 'antonyms', 'hypernyms', 'hyponyms', 'holonyms', 'meronyms',
             'derived', 'related', 'form_of', 'alt_of')

def emit(kind, **data):
    return kind, data

def kaikki(item, path):
    with open_text(path, item.get('compression')) as f:
        for line, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if row.get('lang_code') != item['language'].split('-')[0]:
                continue
            lemma = text(row['word'])
            # Preserve homographs and duplicate source records independently.
            key = identifier(item['source'], item['language'], line, lemma, row.get('pos'), row.get('etymology_number'))
            common = dict(entry_id=key, language=item['language'], locator=str(line))
            yield emit('entries', **common, lemma=lemma, search_key=lemma.casefold(),
                       pos=upos(row.get('pos')), source_pos=row.get('pos', ''),
                       source_page='https://en.wiktionary.org/wiki/' + quote(lemma, safe=''),
                       etymology=str(row.get('etymology_number', '')), entry_type='form' if any(s.get('form_of') for s in row.get('senses', [])) else 'lemma')
            for form in row.get('forms', []):
                if form.get('form'):
                    yield emit('forms', **common, form=text(form['form']), tags=form.get('tags', []),
                               features={}, variety_tags=[t for t in form.get('tags', []) if t in ('Brazil', 'Portugal', 'Brazilian', 'European-Portuguese')])
            for tag in row.get('tags', []):
                yield emit('morphology', **common, features={}, tags=[tag])
            def relations(obj, sense_id=None):
                for relation in RELATIONS:
                    for target in obj.get(relation, []):
                        if target.get('word'):
                            yield emit('relations', **common, sense_id=sense_id, relation=relation,
                                       target=text(target['word']), target_language=item['language'], tags=target.get('tags', []))
                for target in obj.get('translations', []):
                    if target.get('word') and target.get('code'):
                        yield emit('relations', **common, sense_id=sense_id, relation='translation',
                                   target=text(target['word']), target_language=target['code'], tags=target.get('tags', []))
            yield from relations(row)
            for index, sense in enumerate(row.get('senses', [])):
                sid = identifier(key, 'sense', index)
                yield emit('senses', **common, sense_id=sid, glosses=sense.get('glosses', []),
                           gloss_language='en', tags=sense.get('tags', []), source_sense_ids=sense.get('senseid', []))
                yield from relations(sense, sid)


def ud(item, path):
    with open_text(path, item.get('compression')) as f:
        for line, raw in enumerate(f, 1):
            if not raw.strip() or raw.startswith('#'):
                continue
            cols = raw.rstrip('\n').split('\t')
            if len(cols) != 10:
                raise ValueError(f'Invalid CoNLL-U at line {line}')
            if not cols[0].isdigit():  # no multiword ranges or empty nodes
                continue
            _, form, lemma, pos, _, feats, *_ = cols
            if lemma == '_' or pos in ('PUNCT', 'SYM'):
                continue
            lemma = text(lemma)
            key = identifier(item['source'], item['language'], lemma, pos)
            common = dict(entry_id=key, language=item['language'], locator=str(line))
            yield emit('entries', **common, lemma=lemma, search_key=lemma.casefold(), pos=upos(pos),
                       source_pos=pos, source_page=None, etymology='', entry_type='lemma')
            features = {} if feats == '_' else dict(part.split('=', 1) for part in feats.split('|'))
            yield emit('forms', **common, form=text(form), tags=[], features=features, variety_tags=[])
            yield emit('morphology', **common, features=features, tags=[])


def frequency(item, path):
    position, rank, previous = 0, 0, None
    with open_text(path, item.get('compression')) as f:
        for line, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            token, count = raw.rsplit(None, 1)
            count = int(count)
            if count < 0:
                raise ValueError('Negative frequency count')
            position += 1
            if previous is not None and count > previous:
                raise ValueError('Frequency input must be sorted by descending count')
            if count != previous:
                rank = position
            previous = count
            yield emit('frequency', language=item['language'], locator=str(line), lemma=text(token),
                       pos=None, unit='surface', count=count, rank=rank, metric='corpus_count',
                       corpus=item['source'], denominator=None)


def cefr(item, path):
    with open_text(path, item.get('compression')) as f:
        reader = csv.DictReader(f)
        # Native Octanove/CEFR-J header names; canonical TSV/CSV also supported.
        for line, row in enumerate(reader, 2):
            lemma = row.get('headword') or row.get('lemma')
            level = row.get('CEFR') or row.get('cefr_level')
            pos = row.get('pos', '')
            if level not in ('A1', 'A2', 'B1', 'B2', 'C1', 'C2'):
                raise ValueError(f'Invalid CEFR at line {line}: {level}')
            yield emit('cefr', language=item['language'], locator=str(line), lemma=text(lemma),
                       pos=upos(pos), level=level, method='source_asserted', scope='lemma_pos', sense_id=None, notes=row.get('notes', ''))

def ep_frequency(item, path):
    with open_text(path, item.get('compression')) as f:
        for line, row in enumerate(csv.DictReader(f), 2):
            # Only lexical frequency fields; no generated glosses or examples.
            lemma = row.get('lemma') or row.get('word')
            count = int(row['raw_freq'])
            rank = int(row['rank'])
            if count < 0 or rank < 1:
                raise ValueError('Invalid EP frequency')
            yield emit('frequency', language=item['language'], locator=str(line), lemma=text(lemma),
                       pos=upos(row.get('pos', '')), unit='lemma', count=count, rank=rank,
                       metric='corpus_count', corpus=item['source'], denominator=None)

ADAPTERS = {'kaikki': kaikki, 'conllu': ud, 'frequency': frequency, 'cefr': cefr, 'ep_frequency': ep_frequency}
