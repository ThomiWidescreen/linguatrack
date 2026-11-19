# LinguaTrack

An open source, nonprofit language-learning project. One repository for the application and its multilingual lexical-data pipeline.

## Repository layout

| Location | Purpose | Current status |
|---|---|---|
| [`apps/backend/`](apps/backend/) | FastAPI application | Manual lesson ingestion, OpenAI extraction, PostgreSQL learner evidence, background jobs and Swagger; local development without authentication |
| [`packages/lexicon/`](packages/lexicon/) | Python lexical ingestion, normalization, dictionary builds and license audit | Implemented with tests, schemas, synthetic samples and CI |

Start with the [lexical pipeline documentation](packages/lexicon/README.md), [source audit](packages/lexicon/docs/SOURCES.md), and [validation report](packages/lexicon/docs/VALIDATION.md).

## Run the backend

Create a root `.env` from [`.env.example`](.env.example) and set `OPENAI_API_KEY`. If `.env` already exists, keep it and add only missing settings. Then run:

```sh
docker compose up --build -d
```

Open [Swagger](http://localhost:8001/docs) or [ReDoc](http://localhost:8001/redoc). The local API uses a demo user and has no authentication. See [the backend guide](apps/backend/README.md) for a complete two-lesson walkthrough, tests and implementation limits.

## Run the lexical pipeline

```sh
cd packages/lexicon
python -m venv .venv
. .venv/bin/activate
python -m pip install -e . -r requirements-dev.txt
python -m unittest discover -s tests -v
linguatrack-lexicon build --lock examples/synthetic.lock.json --out data/demo --distribution
```

Initial languages: English, Spanish, Portuguese (unspecified, BR and PT kept distinct), and Malay. Real upstream datasets are not committed. Source rights, provenance and release restrictions are tracked separately from software licensing. No frequency-to-CEFR shortcuts or unverified proficiency labels are generated.

## Licensing

Project software and original documentation are [MIT](LICENSE). The project operates without commercial aims; MIT still grants downstream users its standard permissions. Original synthetic example data is CC0. Upstream lexical data retains its own licenses and attribution requirements; it is not relicensed under MIT.

The future application should consume versioned dictionary build artifacts through a documented interface rather than importing unreviewed raw data. Application user data does not belong in the shared dictionary datasets.
