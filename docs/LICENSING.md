# Data rights and release policy

The project is open source and nonprofit. Code is MIT; data permissions are assessed independently. MIT permits downstream commercial use of the code. Licenses with NC restrictions are not classified as unrestricted open data here.

The auditable source registry is `catalog/sources.json`; pinned evidence URLs and observed document checksums are in `catalog/evidence.json`. A review is specific to the documented source and extraction scope. A catalog entry is not a claim that every file at that host is safe to reuse.

`approved` sources have a reviewed ingestion scope. `redistribute` separately controls distribution builds. `quarantined` sources are rejected by both fetch and build. There is no CLI bypass for quarantined sources: a contributor must supply evidence and change the reviewed catalog. NC sources additionally require `--allow-nc`, and NC/open sources cannot share a build. Different share-alike licenses cannot share a distribution build. This conservative rule avoids implying that incompatible obligations disappear in a combined artifact.

For each new source/revision, record:

1. Original creator, authoritative publisher, intermediate transformations and immutable release/commit.
2. Data license separately from software license; exact scope, attribution, share-alike and NC obligations.
3. License/terms URL, checked date and observed evidence checksum. Do not infer a grant from a GitHub badge or a mirror.
4. Exact input checksum, immutable URL where possible, language/variety, format and excluded fields.
5. Required credits/citations and changes made by our adapter.

For releases, retain generated `ATTRIBUTION.md`, manifest, per-row licenses and license links. Share-alike adaptations remain under the relevant upstream license; no blanket MIT data license is applied. Wiktionary source page URLs identify the original entries and provide access to contributor histories. Retain Kaikki/Wiktextract citation and extraction details. Sentence quotations, examples and media are omitted because their rights can differ from lexical text.

Current automated controls enforce reviewed source status, language/format, checksums, provenance presence, redistribution status and separation of license families. They do not adjudicate novel copyright questions. When evidence is incomplete, the source stays quarantined even if research access is free or our intended use is nonprofit.
