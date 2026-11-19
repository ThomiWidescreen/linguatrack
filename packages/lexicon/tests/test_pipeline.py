import copy
import json
import gzip
import io
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path
from linguatrack_lexicon.build import build
from linguatrack_lexicon.core import read_json, digest, canonical, validate_lock
from linguatrack_lexicon.adapters import kaikki, ud, cefr, frequency

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / 'catalog/sources.json'
LANG = ROOT / 'catalog/languages.json'
LOCK = ROOT / 'examples/synthetic.lock.json'

class PipelineTests(unittest.TestCase):
    def run_build(self, path):
        return build(LOCK, CAT, LANG, path, distribution=True)

    def test_reproducible_and_all_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'a', Path(tmp)/'b'
            ma, mb = self.run_build(a), self.run_build(b)
            self.assertEqual(ma, mb)
            self.assertEqual({p.name:p.read_bytes() for p in a.iterdir()}, {p.name:p.read_bytes() for p in b.iterdir()})
            rows = [json.loads(x) for x in (a/'entries.jsonl').read_text().splitlines()]
            self.assertEqual({r['language'] for r in rows}, {'en','es','pt','pt-BR','pt-PT','ms'})
            self.assertEqual(ma['counts']['cefr'], 1)
            for filename, checksum in ma['files'].items():
                self.assertEqual(digest(a/filename), checksum)

    def test_checksum_and_failed_build_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = read_json(LOCK)
            for item in lock['inputs']:
                item['path'] = str(LOCK.parent/item['path'])
            lock['inputs'][0]['sha256'] = '0'*64
            p = Path(tmp)/'lock.json';p.write_text(canonical(lock))
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                build(p, CAT, LANG, Path(tmp)/'out')
            self.assertFalse((Path(tmp)/'out').exists())

    def test_quarantine_and_nc(self):
        lock, cat, languages = read_json(LOCK), read_json(CAT), read_json(LANG)
        item = copy.deepcopy(lock['inputs'][0]);item.update(source='cefr-j',format='cefr')
        with self.assertRaisesRegex(ValueError, 'quarantined'):
            validate_lock({'version':1,'inputs':[item]}, cat, languages)
        item['source']='nc-test'; cat['nc-test']={**cat['synthetic'], 'noncommercial':True}
        with self.assertRaisesRegex(ValueError, 'allow-nc'):
            validate_lock({'version':1,'inputs':[item]},cat,languages)
        validate_lock({'version':1,'inputs':[item]},cat,languages,allow_nc=True)
        with self.assertRaisesRegex(ValueError,'Mixed NC'):
            validate_lock({'version':1,'inputs':[item,lock['inputs'][1]]},cat,languages,allow_nc=True)

    def test_reject_unapproved_redistribution(self):
        lock, cat, languages = read_json(LOCK), read_json(CAT), read_json(LANG)
        cat[lock['inputs'][0]['source']]['redistribute'] = False
        with self.assertRaisesRegex(ValueError,'Redistribution not approved'):
            validate_lock(lock,cat,languages,distribution=True)

    def test_invalid_format_language_digest_duplicate(self):
        for field, value in [('format','arbitrary'),('language','id'),('sha256','bad')]:
            lock=read_json(LOCK);lock['inputs'][0][field]=value
            with self.assertRaises(ValueError):
                validate_lock(lock,read_json(CAT),read_json(LANG))
        lock=read_json(LOCK);lock['inputs'].append(lock['inputs'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            validate_lock(lock,read_json(CAT),read_json(LANG))

    def test_ud_skip_ranges_empty_missing_lemma_and_preserve_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ud'
            p.write_text('1-2\tdel\t_\t_\t_\t_\t_\t_\t_\t_\n1\tdo\tdar\tVERB\t_\tMood=Ind|Person=1\t0\troot\t_\t_\n1.1\tx\tx\tX\t_\t_\t0\tdep\t_\t_\n2\tx\t_\tX\t_\t_\t0\tdep\t_\t_\n')
            rows=list(ud({'source':'test','language':'es'},p))
            self.assertEqual(len(rows),3)
            self.assertEqual(rows[1][1]['features'],{'Mood':'Ind','Person':'1'})
            p.write_text('invalid\n')
            with self.assertRaises(ValueError):list(ud({'source':'test','language':'es'},p))

    def test_nfc_case_homographs_and_form_of(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'lex'
            r={'word':'cafe\u0301','lang_code':'pt','pos':'noun','senses':[{'glosses':['a test']}], 'etymology_number':1}
            r2={**r,'etymology_number':2,'senses':[{'form_of':[{'word':'root'}]}]}
            p.write_text(json.dumps(r)+'\n'+json.dumps(r2)+'\n'+json.dumps({**r,'lang_code':'id'})+'\n')
            rows=list(kaikki({'source':'test','language':'pt'},p))
            entries=[r for k,r in rows if k=='entries']
            self.assertEqual(len(entries),2)
            self.assertEqual(entries[0]['lemma'],'café')
            self.assertNotEqual(entries[0]['entry_id'],entries[1]['entry_id'])
            self.assertEqual(entries[1]['entry_type'],'form')
            self.assertEqual(entries[1]['language'],'pt')
            self.assertTrue(any(k=='relations' and r['relation']=='form_of' for k,r in rows))

    def test_bad_cefr_and_frequency_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data'; p.write_text('headword,pos,CEFR\nx,noun,D1\n')
            with self.assertRaises(ValueError):list(cefr({'language':'en'},p))
            p.write_text('x -1\n')
            with self.assertRaises(ValueError):list(frequency({'language':'en','source':'test'},p))

    def test_frequency_ties_and_unsorted_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'freq';p.write_text('a 10\nb 10\nc 2\n')
            self.assertEqual([r['rank'] for _,r in frequency({'language':'en','source':'s'},p)],[1,1,3])
            p.write_text('a 2\nb 10\n')
            with self.assertRaisesRegex(ValueError,'sorted'):
                list(frequency({'language':'en','source':'s'},p))

    def test_gzip_kaikki(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'input.gz'
            with gzip.open(p,'wt',encoding='utf-8') as out:
                out.write(json.dumps({'word':'Test','lang_code':'en','pos':'noun'})+'\n')
            row=list(kaikki({'source':'s','language':'en','compression':'gzip'},p))[0][1]
            self.assertEqual(row['lemma'],'Test')
            self.assertEqual(row['search_key'],'test')
            self.assertEqual(row['source_page'],'https://en.wiktionary.org/wiki/Test')

    def test_parse_failure_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bad=root/'bad.jsonl';bad.write_text('{invalid')
            item=read_json(LOCK)['inputs'][0]
            item.update(path='bad.jsonl',sha256=digest(bad))
            lock=root/'lock.json';lock.write_text(canonical({'version':1,'inputs':[item]}))
            with self.assertRaises(ValueError):build(lock,CAT,LANG,root/'out')
            self.assertFalse((root/'out').exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()),['bad.jsonl','lock.json'])

    def test_different_sharealike_release_blocked(self):
        lock=read_json(ROOT/'catalog/production.lock.json')
        with self.assertRaisesRegex(ValueError,'share-alike'):
            validate_lock(lock,read_json(CAT),read_json(LANG),distribution=True)

    def test_shared_input_multiple_languages(self):
        lock=read_json(LOCK);item=copy.deepcopy(lock['inputs'][0])
        cat=read_json(CAT);cat[item['source']]['languages'].append('es')
        second={**item,'language':'es'}
        validate_lock({'version':1,'inputs':[item,second]},cat,read_json(LANG))

    def test_fetch_download_and_mismatch_cleanup(self):
        from linguatrack_lexicon.cli import fetch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);expected=root/'expected';expected.write_bytes(b'payload')
            lock=read_json(LOCK);item=copy.deepcopy(lock['inputs'][0])
            item.update(path='download',sha256=digest(expected),synthetic=False)
            lock={'version':1,'inputs':[item]};lp=root/'lock.json';lp.write_text(canonical(lock))
            def response(payload):
                r=io.BytesIO(payload);r.url='https://example.org/file';return r
            with patch('urllib.request.urlopen',return_value=response(b'wrong')):
                with self.assertRaisesRegex(ValueError,'checksum'):
                    fetch(lp,CAT,LANG)
            self.assertFalse((root/'download').exists())
            with patch('urllib.request.urlopen',return_value=response(b'payload')):
                fetch(lp,CAT,LANG)
            self.assertEqual((root/'download').read_bytes(),b'payload')

    def test_schema_validation(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('Install requirements-dev.txt for JSON Schema validation')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';self.run_build(out)
            for file in out.glob('*.jsonl'):
                schema=read_json(ROOT/'schemas'/(file.stem+'.schema.json'))
                jsonschema.Draft202012Validator.check_schema(schema)
                for line in file.read_text().splitlines():
                    jsonschema.validate(json.loads(line),schema)

if __name__ == '__main__':
    unittest.main()
