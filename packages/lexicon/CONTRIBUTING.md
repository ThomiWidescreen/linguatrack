# Contributing

Keep the project independent, open source and nonprofit. Contributions to software/docs are MIT; new original synthetic fixtures are CC0. Do not submit proprietary, scraped or unlicensed dictionary contents in a pull request.

To add a language: register its BCP-47 code/base in `catalog/languages.json`, review source language/variety support, add original fixtures, and test Unicode, case and morphology behavior. Do not alias related languages or silently flatten dialects.

To add a source/adapter: follow `docs/LICENSING.md`, start quarantined, implement a streaming generator of `(table, assertion)` records with line locators in `adapters.py`, register the format and approved source/language combinations, and add meaningful adapter, failure, provenance and reproducibility tests. Unknown data must stay unknown. Update schemas if output changes; version breaking changes explicitly.

Run `python -m unittest discover -s tests -v`. CI validates JSON Schemas and byte-for-byte synthetic builds on Python 3.11–3.13. Large public datasets never need to be downloaded for a code-only contribution. Record real integration runs separately; don't fabricate coverage statistics from tiny fixtures.
