# Canonical dictionary model 1.0

Machine-readable schemas: [`../schemas/`](../schemas/). Output is normalized assertion tables, suitable for loading into SQL or a graph store. They are not one nested JSON object per word.

| Table | Identity / content | Scope |
|---|---|---|
| entries | `entry_id`, lemma, casefold search key, UPOS, source POS, etymology, entry type, source page | Source-specific lexical entry assertions |
| forms | entry reference, surface form, source tags, features, variety tags | Multiple analyses of the same spelling are retained |
| senses | entry reference, sense ID, glosses, gloss language, source IDs and tags | Sense segmentation stays source-specific |
| morphology | entry reference, feature map, original tags | UD features retained without inventing a complete paradigm |
| relations | entry reference, optional sense ID, relation, target text and target language | Entry- and sense-level edges; targets may remain unresolved |
| frequency | lexical text, optional POS, unit, count, rank, corpus and optional denominator | Corpus-specific observations, not sense probabilities |
| cefr | lexical text, POS, level, source method, scope, optional sense and notes | Source-asserted anchors, independent of dictionary sense alignment |

Every row includes a content-addressed assertion `id`, `schema_version`, `language` and `provenance` with source ID, exact input SHA-256, source revision, input line locator, license, upstream URL, confidence and confidence basis. Content-addressed IDs are stable for the same snapshot; reordering or replacing source bytes can change IDs. They are not permanent Wiktionary page/sense IDs.

`entry_id` identifies a source lexical entry; multiple assertions may refer to it (for example repeated UD token observations). Consumers should group by `entry_id` when enumerating entries. Kaikki homographs retain separate source-line/etymology identities; UD supplies lemma+POS observations without inventing etymological distinctions. No automatic cross-source equivalence is asserted. A Kaikki entry marked through `form_of` remains a form entry and keeps its edge to the lemma, rather than being counted unconditionally as a new lemma.

Case and accents are preserved. Only the separate search key is casefolded. Whitespace at lexical field boundaries is trimmed. There is no stemming, ASCII transliteration or automatic Malay root-family collapsing. Multiword lexemes remain strings. Unknown POS becomes `X` and the source POS is preserved on entries.

Kaikki form tags remain source tags rather than being mislabeled as universal grammatical features. UD's feature maps preserve its feature names and values. Sense tags can contain grammatical and regional qualifications. Entry-wide dialect inference is intentionally absent. Form-specific variety tags are preserved, and full tags remain available.

FrequencyWords provides surface counts: no context-free lemmatization is attempted, and POS is null. Ranks use competition ranking over the descending input list, retaining ties. EPspokenfrequency provides lemma/POS counts and upstream ranks from a different, filtered corpus. A truncated input list does not provide the full corpus denominator, so it stays null. Do not sum across corpora, compare raw counts across languages, or treat missing frequencies as zero. Match observations conservatively by language, text, unit and POS; no surface-to-lemma join is built in.

CEFR notes are preserved because headword+POS labels may hide sense distinctions. No anchor is assigned to a dictionary sense without alignment evidence. Missing levels mean unknown, not A1. Conflicting levels from multiple sources remain separate assertions.

Confidence 0.9 is explicitly an **import-fidelity heuristic**, identical across imports; it is not a calibrated probability that the linguistic claim or proficiency level is correct. Keep this basis visible in downstream applications. No artificial differences in confidence between languages are introduced.
