# LinguaTrack applications

Application code lives here, separately from the lexical-data pipeline.

- [`backend/`](backend/README.md): FastAPI + PostgreSQL, manual lesson ingestion through OpenAI, background processing, learner evidence and Swagger. Local development without authentication.

Use `../packages/lexicon/` to build the reference dictionary tables. Preserve each artifact's manifest, provenance and data license obligations when integrating them into the application. Keep learner knowledge, learning events and assessment results separate from the reference dictionaries.

The broader design is documented in [the backend architecture proposal](../docs/backend-architecture.md). See the backend README for the implemented scope and deferred features.
