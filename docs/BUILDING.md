# Reproducible acquisition and builds

Run commands from the repository root. The CLI also accepts explicit `--catalog` and `--languages` paths before the subcommand, so an installed package can work with a separately managed source registry.

## Lock contract

A version-1 lock has `inputs`: each item names an approved catalog source, language, adapter format, path relative to the lock file, HTTPS URL, immutable revision description and a 64-character SHA-256 checksum. Optional compression is `gzip`. The lock is a trusted build configuration, not a security boundary for hostile paths or URLs. Never run an unreviewed third-party lock.

`fetch` downloads only absent files, streams bytes to temporary files, verifies the entire checksum, then installs them. Existing mismatched files are rejected. `build` rechecks every input before parsing, including inputs already present locally. A build never overwrites an existing output directory.

## Acquire Kaikki raw English-edition data

Read https://kaikki.org/dictionary/rawdata.html first and record the dump date and extractor revisions shown there. The current combined gzip dump is several GB; allow disk space for both acquisition and disk-backed staging. Use the raw English-edition URL, not the website's postprocessed language exports.

```sh
linguatrack-lexicon snapshot   --source kaikki-en-raw --language en --format kaikki   --url https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz   --revision 'enwiktionary dump 2026-10-01; extraction 2026-10-30; wiktextract 19f9a30/6f96ddf; observed snapshot'   --compression gzip --file data/raw/kaikki-en.jsonl.gz   --lock catalog/kaikki-en.local.lock.json
linguatrack-lexicon build --lock catalog/kaikki-en.local.lock.json --out data/kaikki-en --distribution
```

**Update the revision description from the live raw-data page when acquiring.** These sample dates describe the reviewed page, not a guarantee that its rotating download still contains those bytes. `snapshot` computes the observed checksum; it is trust on first HTTPS acquisition, not publisher signature verification. Archive the downloaded bytes because a rotating URL may stop serving the locked snapshot. Later `fetch` fails on changed bytes instead of silently updating a build.

To build all four base languages from the same raw file, copy the locked input for `en`, `es`, `pt`, and `ms` into one new lock. Retain the same path, URL, revision and checksum; change only `language`. The adapter currently scans once per requested language, so four-language builds trade extra reading time for bounded memory. The duplicate-input check rejects identical inputs while allowing these distinct language selections.

The adapter only supports the English-edition field contract. Other Wiktionary editions require separate adapters because gloss language and field meanings differ.

## Select source subsets

```sh
python scripts/select_lock.py catalog/production.lock.json catalog/en-open.local.lock.json frequencywords-en octanove-c1c2
linguatrack-lexicon build --lock catalog/en-open.local.lock.json --out data/en-open --distribution
python scripts/select_lock.py catalog/production.lock.json catalog/en-pud.local.lock.json ud-en-pud
linguatrack-lexicon build --lock catalog/en-pud.local.lock.json --out data/en-pud --distribution
```

Use the same selector for language-specific tables, for example `frequencywords-ms`, `frequencywords-pt-BR` or `ep-spoken`. Unmarked Portuguese layers stay independent of either regional layer.

## Distribution

Use a fresh output directory and `--distribution`. Its checks are preflight policy checks against the audited catalog; they do not turn a new upstream release into an automatically reviewed one. Split CC BY-SA 3.0, CC BY-SA 4.0 and NC releases. Copy all output files together, retain attribution, source page links, source licenses and modification notices. Do not publish `data/` by removing `.gitignore`.

## Determinism

Records and output ordering are content-addressed and canonical JSON (UTF-8, NFC lexical text, sorted keys, no NaN, Unix line endings). Input bytes, source/language catalogs and pipeline version determine the logical build. Python version is recorded; compare byte-for-byte on the same runtime, or ignore only the `python` manifest field when comparing runtime versions. No build timestamps or absolute local paths are injected. Lock paths remain relative for portability. SQLite is an implementation detail for disk-backed staging and is not exported.

Malformed records fail the entire build. There is no silent best-effort quarantine inside approved files; unexpected schema changes must be reviewed and fixed. Raw inputs and successful previous builds survive failures.
