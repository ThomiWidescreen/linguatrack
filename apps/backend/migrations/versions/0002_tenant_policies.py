"""Tenant policies, immutable evidence and initial language catalog.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PRIVATE = (
    "user_languages",
    "learning_sessions",
    "processing_runs",
    "ingestion_requests",
    "learning_observations",
    "user_knowledge_state",
    "evidence_amendments",
    "outbox",
)
TENANT = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade():
    languages = sa.table("languages", sa.column("tag"), sa.column("name"), sa.column("base_tag"))
    op.bulk_insert(
        languages,
        [
            {"tag": "en", "name": "English", "base_tag": "en"},
            {"tag": "es", "name": "Spanish", "base_tag": "es"},
            {"tag": "pt", "name": "Portuguese, unspecified variety", "base_tag": "pt"},
            {"tag": "pt-BR", "name": "Brazilian Portuguese", "base_tag": "pt"},
            {"tag": "pt-PT", "name": "European Portuguese", "base_tag": "pt"},
            {"tag": "ms", "name": "Malay", "base_tag": "ms"},
        ],
    )
    for table in (*PRIVATE, "users", "concepts", "concept_embeddings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for table in PRIVATE:
        op.execute(
            f"CREATE POLICY tenant ON {table} USING (user_id = {TENANT}) WITH CHECK (user_id = {TENANT})"
        )
    op.execute(f"CREATE POLICY tenant ON users USING (id = {TENANT}) WITH CHECK (id = {TENANT})")
    op.execute(f"""CREATE POLICY tenant ON concepts
        USING (owner_user_id IS NULL OR owner_user_id = {TENANT})
        WITH CHECK (owner_user_id = {TENANT})""")
    op.execute("""CREATE POLICY tenant ON concept_embeddings FOR SELECT USING (
        EXISTS (SELECT 1 FROM concepts WHERE concepts.id = concept_embeddings.concept_id))""")
    op.execute("GRANT USAGE ON SCHEMA public TO linguatrack_app")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO linguatrack_app")
    for table in (
        "users",
        "user_languages",
        "concepts",
        "ingestion_requests",
        "learning_observations",
        "evidence_amendments",
    ):
        op.execute(f"GRANT INSERT ON {table} TO linguatrack_app")
    for table in ("learning_sessions", "processing_runs", "outbox"):
        op.execute(f"GRANT INSERT, UPDATE ON {table} TO linguatrack_app")
    op.execute("GRANT INSERT, UPDATE, DELETE ON user_knowledge_state TO linguatrack_app")
    op.execute("""
        CREATE FUNCTION validate_observation() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE concept_owner uuid; concept_language text; session_language text;
        BEGIN
            SELECT owner_user_id, language_tag INTO concept_owner, concept_language
                FROM concepts WHERE id = NEW.concept_id;
            IF concept_language IS NULL OR (concept_owner IS NOT NULL AND concept_owner <> NEW.user_id) THEN
                RAISE EXCEPTION 'Inaccessible concept';
            END IF;
            SELECT t.language_tag INTO session_language FROM learning_sessions s
                JOIN user_languages t ON t.id = s.track_id AND t.user_id = s.user_id
                JOIN processing_runs r ON r.id = NEW.run_id AND r.session_id = s.id
                WHERE s.id = NEW.session_id AND s.user_id = NEW.user_id;
            IF session_language IS NULL OR session_language <> concept_language THEN
                RAISE EXCEPTION 'Observation session, run or language mismatch';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER validate_observation BEFORE INSERT ON learning_observations
            FOR EACH ROW EXECUTE FUNCTION validate_observation();
        CREATE FUNCTION validate_publication() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.text <> OLD.text OR NEW.source <> OLD.source
                OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
                OR NEW.user_id <> OLD.user_id OR NEW.track_id <> OLD.track_id THEN
                RAISE EXCEPTION 'Original lesson content and ownership are immutable';
            END IF;
            IF NEW.published_run_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM processing_runs r WHERE r.id = NEW.published_run_id
                    AND r.session_id = NEW.id AND r.user_id = NEW.user_id
            ) THEN RAISE EXCEPTION 'Invalid published run'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER validate_publication BEFORE UPDATE ON learning_sessions
            FOR EACH ROW EXECUTE FUNCTION validate_publication();
    """)


def downgrade():
    op.execute("DROP TRIGGER validate_publication ON learning_sessions")
    op.execute("DROP FUNCTION validate_publication()")
    op.execute("DROP TRIGGER validate_observation ON learning_observations")
    op.execute("DROP FUNCTION validate_observation()")
    for table in (*PRIVATE, "users", "concepts", "concept_embeddings"):
        op.execute(f"DROP POLICY tenant ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
