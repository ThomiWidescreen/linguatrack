# Validation report — 19 November 2026

## Offline checks

15 unit/integration tests passed locally, including schema validation, byte-identical repeated builds, SHA mismatch rejection, atomic parse failures, download integrity/cleanup, NFC/case preservation, homographs, form-of relations, CoNLL-U multiword/empty-node handling, frequency ties, gzip, shared language-filtered inputs and license gates.

Committed synthetic artifacts cover en, es, pt, pt-BR, pt-PT and ms. Their semantic edges, CEFR levels and counts are illustrative only.

## Real pinned integration build

Command: `linguatrack-lexicon build --lock catalog/production.lock.json --out data/verified-final`.

All ten files were acquired from commit-pinned upstream URLs and checksum-verified. The build completed; no real source text or derived data from this run is committed. These are **assertion counts**, not unique lemmas or evidence of full language coverage.

| Table | Assertions | Rows additionally checked against JSON Schema |
|---|---:|---:|
| cefr | 2,136 | 1,000 |
| entries | 90,384 | 1,000 |
| forms | 90,384 | 1,000 |
| frequency | 255,000 | 1,000 |
| morphology | 90,384 | 1,000 |
| relations | 0 | 0 |
| senses | 0 | 0 |

Every input checksum was checked. Output manifests record each output checksum. Schema sampling covers the first 1,000 rows of each populated real table; offline tests fully validate all synthetic rows. This report does not claim exhaustive schema validation of the large real integration output.

The lock includes FrequencyWords 50k lists (five language/variety labels), EPspokenfrequency top5000, UD English PUD test / Spanish AnCora dev / Portuguese Bosque dev, and the 2,136-row Octanove C1/C2 file. UD contributes token observations; repeated lemma/POS entries should be grouped by entry_id for unique entry counts.

## Raw Kaikki prefix smoke

An HTTPS read of at most 4 MiB from the original English-edition raw JSONL endpoint retained only complete lines. It is a convenience sample from the start of the stream, **not a random sample or a full dump**, and is excluded from git. All four requested base languages occur in this prefix.

Observed sample: 4,159,523 bytes; SHA-256 `d1fb54d9917186dbbc47a48ae28bbe545dd1e1501fb53696c79d531957d89ac9`. This checksum identifies the observed prefix only, not the upstream full dump.

| Language | Entries | Forms | Senses | Relations |
|---|---:|---:|---:|---:|
| en | 103 | 288 | 391 | 14,920 |
| es | 10 | 6 | 15 | 124 |
| pt | 10 | 7 | 14 | 93 |
| ms | 5 | 9 | 5 | 59 |

All 16,059 assertions emitted by the raw adapter for en/es/pt/ms passed the published JSON Schemas. It preserves source-specific senses and entry/sense-level relations without quoting corpus examples. The full Kaikki acquisition/build remains an explicit large-data operation documented in BUILDING.md; it was not run for all languages during this initialization.

## CI

GitHub Actions runs tests, schema checks and reproducibility checks on Python 3.11, 3.12 and 3.13 without downloading datasets. Runtime versions are recorded in manifests, so CI compares committed artifacts with only that runtime field excluded. CI does not upload real data as an artifact or publish dataset releases automatically.

## Known gaps

No complete major-language dictionary release, isolated production morphology layer for pt-BR/pt-PT, Malay UD source, validated A1–B2 English anchors, or reusable Spanish/Portuguese/Malay CEFR layer is claimed. The architecture supports adding audited sources without filling these gaps with guesses. Corpus/domain bias and import-confidence heuristics must remain visible to downstream consumers.
