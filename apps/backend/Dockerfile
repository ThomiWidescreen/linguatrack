FROM python:3.12-slim
WORKDIR /app
COPY apps/backend/pyproject.toml ./
COPY apps/backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY apps/backend/src ./src
RUN pip install --no-cache-dir --no-deps .
COPY apps/backend/alembic.ini ./
COPY apps/backend/migrations ./migrations
COPY packages/lexicon/schemas ./packages/lexicon/schemas
CMD ["uvicorn", "linguatrack.main:app", "--host", "0.0.0.0", "--port", "8000"]
