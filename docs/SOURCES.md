# Source and provenance audit — 19 November 2026

The earlier ChatGPT discussion supplied leads, not verified permissions. This audit rechecked primary project/publisher pages and kept unresolved leads out of ingestion. Authoritative URLs and decisions are machine-readable in [`../catalog/sources.json`](../catalog/sources.json); reviewed Git evidence has commit-pinned URLs and checksums in [`../catalog/evidence.json`](../catalog/evidence.json).

| Source | Decision | Scope / caveat |
|---|---|---|
| [Kaikki raw / Wiktextract](https://kaikki.org/dictionary/rawdata.html) | Approved lexical adapter | English-edition raw data only; CC BY-SA 4.0 Wiktionary lexical text. Extractor code MIT is separate. No website postprocessing, quotes, examples or media. Full multi-GB dump not included in smoke build. |
| [FrequencyWords](https://github.com/hermitdave/FrequencyWords) | Approved, pinned | OpenSubtitles 2018 surface counts for en/es/pt/pt_br/ms. Content CC BY-SA 4.0; code MIT. Corpus labels and subtitle bias retained. |
| [UD English PUD](https://github.com/UniversalDependencies/UD_English-PUD) | Approved, pinned | CC BY-SA 3.0; test split, lexical morphology only. Separate distribution artifact. |
| [UD Spanish AnCora](https://github.com/UniversalDependencies/UD_Spanish-AnCora) | Approved, pinned | Current LICENSE and metadata CC BY 4.0; README retains stale GNU wording. v2.9 change explains transition. Dev split only. |
| [UD Portuguese Bosque](https://github.com/UniversalDependencies/UD_Portuguese-Bosque) | Approved, pinned | CC BY-SA 4.0; mixed BR/PT corpus remains pt. Dev split only. |
| [UD English EWT](https://github.com/UniversalDependencies/UD_English-EWT) | Quarantined | Annotation/database CC BY-SA does not establish all underlying LDC text rights. |
| [UD English GUM](https://github.com/UniversalDependencies/UD_English-GUM) | NC, quarantined | CC BY-NC-SA 4.0; document-specific attribution needs implementation before adoption. Nonprofit intent alone does not resolve those obligations. |
| UD Malay | Coverage gap | No Malay repository found in the reviewed UD organization search. Malayalam and Indonesian must not be substituted. |
| [EPspokenfrequency](https://github.com/professorcdp/EPspokenfrequency) | Approved, pinned | Jim Ranalli's CC BY-SA 4.0 frequency columns only; top5000 shard. Portugal-tagged subtitles are a noisy signal. Generated glosses/examples excluded. |
| [Octanove C1/C2](https://github.com/openlanguageprofiles/olp-en-cefrj) | Approved, pinned | Explicit CC BY-SA 4.0 grant for this specific file. Source-asserted English anchors, no invented A1–B2 coverage. |
| CEFR-J vocabulary/grammar | Quarantined | Research/commercial use with citation is stated, but redistribution permission needs clarification. Do not conflate its terms with Octanove's explicit CC license. |
| [wordfreq](https://github.com/rspeer/wordfreq/blob/master/NOTICE.md) | Surveyed alternative | Composite data CC BY-SA 4.0 with notices/credits; software Apache. Native package ingestion deferred; generic pt does not establish pt-BR/PT-PT and Malay coverage is unverified. |
| [wordhoard](https://github.com/natema/wordhoard) | Quarantined derivative | Declares CC BY-SA data/MIT code; source table labels FrequencyWords MIT, unlike that upstream's content license. Non-German CEFR estimates are not validated anchors. Use primary inputs first. |
| [fserb/pt-br](https://github.com/fserb/pt-br) | Quarantined | Mixed dictionary origins; sufficient upstream grants not established. |
| [Community CEFR](https://github.com/Talhakasikci/cefr-vocabulary-dataset) | Quarantined | Oxford-derived content and personal/educational-use wording; origin rights unresolved. |
| [Cervantes scraper](https://github.com/Heartade/spanish-words-cefr) | Quarantined | Author explicitly withholds extracted data over redistribution uncertainty. |
| [Oxford lists](https://www.oxfordlearnersdictionaries.com/wordlists/oxford3000-5000), [Cambridge EVP](https://www.englishprofile.org/) | Reference leads only | No reusable bulk data grant verified; Oxford page returned 403. No scraping or extracted contents distributed. |
| [Leipzig](https://wortschatz.uni-leipzig.de/en/download) | Quarantined | Anti-bot page prevented exact package review; conflicting mirror labels are not accepted as evidence. |
| P-PAL, [LexMAL / Malay Lexicon Project lead](https://pmc.ncbi.nlm.nih.gov/articles/PMC11289131/) | Unverified leads | Package/database redistribution terms not established. A paper's license does not automatically cover a separate database. |

## Language coverage

| Language | Dictionary architecture | Real frequency smoke | Real morphology smoke | Approved CEFR |
|---|---|---|---|---|
| en | Kaikki adapter + synthetic fixture | FrequencyWords | UD PUD | Octanove C1/C2 |
| es | Kaikki adapter + synthetic fixture | FrequencyWords | UD AnCora | None verified |
| pt | Kaikki adapter + synthetic fixture | FrequencyWords | Mixed Bosque | None verified |
| pt-BR | Explicit variant fixture | pt_br FrequencyWords | No isolated production layer yet | None verified |
| pt-PT | Explicit variant fixture | EPspokenfrequency | No isolated production layer yet | None verified |
| ms | Kaikki adapter + synthetic fixture | FrequencyWords | No verified UD layer | None verified |

This is an extensible baseline with documented gaps, not an assertion of complete language coverage. Real sense/semantic-relation coverage requires running the separately acquired full Kaikki input. No calibrated CEFR lexical-size estimates are supplied.
