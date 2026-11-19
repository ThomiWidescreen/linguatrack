# LinguaTrack Lexicon

An independent, open source, nonprofit multilingual lexical-data pipeline for LinguaTrack and other learning tools. Python 3.11+, no runtime dependencies.

It builds **provenance-preserving dictionary tables**, not a certified proficiency curriculum. Initial language registry: English (`en`), Spanish (`es`), Portuguese unspecified (`pt`), Brazilian Portuguese (`pt-BR`), European Portuguese (`pt-PT`), and Malay (`ms`).

## Quick start

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e . -r requirements-dev.txt
python -m unittest discover -s tests -v
linguatrack-lexicon build --lock examples/synthetic.lock.json --out data/demo --distribution
```

Inspect `examples/output/` for a committed tiny build. **All committed example lexical data is authored, synthetic CC0 material.** The CEFR example is illustrative, not a teaching recommendation.

Each build emits sorted JSONL tables for entries, inflected forms, senses, morphology, semantic relations, frequency observations and CEFR anchors, plus `manifest.json` and `ATTRIBUTION.md`. Every assertion includes its source, source revision, exact input checksum, line locator, license and import-confidence basis. Builds stage on disk and publish only after validation succeeds.

## Real data

`catalog/production.lock.json` pins ten modest upstream files to immutable Git commits and SHA-256 checksums: five FrequencyWords lists, English/Spanish/Portuguese UD samples, European Portuguese lemma frequencies, and English Octanove C1/C2 anchors. Raw files and derived real-data outputs are gitignored.

```sh
linguatrack-lexicon fetch --lock catalog/production.lock.json
linguatrack-lexicon build --lock catalog/production.lock.json --out data/real-local
```

This is a real **integration smoke build**, not complete dictionary coverage: UD files are a dev/test split, frequency lists are truncated, and the full Kaikki dump is not bundled or downloaded by CI. See [coverage and validation](docs/VALIDATION.md).

For public artifacts, use `--distribution`. It rejects quarantined/non-redistributable sources and mixing different share-alike licenses. English PUD is CC BY-SA 3.0; keep its release separate from CC BY-SA 4.0 layers. The lock is readable JSON: create a new lock with only the relevant inputs, retaining exact metadata and relative paths. Preserve the generated notices and upstream license links with any distribution.

## Kaikki / Wiktextract

The adapter consumes **English Wiktionary edition raw JSONL**, optionally gzip-compressed, filtering on lexical language. That edition supplies English glosses even for Spanish, Portuguese and Malay. See the [acquisition recipe](docs/BUILDING.md) for snapshotting a large raw dump once, then building the four languages. Postprocessed per-language download links are deprecated upstream and may merge other sources; they are deliberately outside the approved ingestion scope.

## License boundaries

Software and project-authored documentation: [MIT](../../LICENSE). Original synthetic fixtures: [CC0](examples/README.md). Upstream data retains its own terms; it is **not covered by MIT**. The nonprofit mission does not revoke the permissions MIT grants downstream users. Noncommercial-only data is a distinct category and cannot be mixed into open share-alike releases by this pipeline.

Read the [license and provenance audit](docs/SOURCES.md), [policy](docs/LICENSING.md), [canonical model](docs/SCHEMA.md), and [contribution guide](CONTRIBUTING.md). Public availability, an open scraper, or a repository-level license alone does not establish rights in copied third-party data.

## Deliberate limitations

- No automatic frequency-to-CEFR mapping, word-count thresholds, or cross-language proficiency equivalence.
- No verified reusable CEFR anchor layer for Spanish, Portuguese or Malay in this initial audit. English has C1/C2 anchors only; CEFR-J A1–B2 is quarantined pending a clearer redistribution grant.
- No automatic alignment of homographs, senses, or corpus surface counts to dictionary lemmas. Records stay separate by source and scope.
- Portuguese labels reflect source evidence: general Kaikki and mixed Bosque stay `pt`; unmarked entries are not cloned into BR/PT.
- No audio, quotations, copied example sentences, generated definitions, or scraped proprietary word lists are exported.
