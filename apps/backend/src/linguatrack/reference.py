import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from linguatrack.config import ROOT, get_settings
from linguatrack.db import advisory_lock
from linguatrack.models import Concept, ReferenceAssertion, ReferenceBuild
from linguatrack.schemas import digest
from linguatrack.services import normalize

TABLES = ("entries", "forms", "senses", "morphology", "relations", "frequency", "cefr")


def import_build(directory: Path, allow_nc: bool = False):
    """Import reviewed build artifacts atomically; source assertions never become user data."""
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    build_digest = hashlib.sha256(manifest_bytes).hexdigest()
    validators = {}
    for kind in TABLES:
        path = directory / f"{kind}.jsonl"
        with path.open("rb") as raw:
            checksum = hashlib.file_digest(raw, "sha256").hexdigest()
        if checksum != manifest["files"][path.name]:
            raise ValueError(f"Artifact checksum mismatch: {path.name}")
        schema = json.loads((ROOT / "packages/lexicon/schemas" / f"{kind}.schema.json").read_text())
        validators[kind] = Draft202012Validator(schema)
        count = 0
        with path.open() as lines:
            for line in lines:
                row = json.loads(line)
                validators[kind].validate(row)
                provenance = row["provenance"]
                source = manifest["sources"][provenance["source"]]
                if source["status"] != "approved":
                    raise ValueError("Unreviewed or quarantined source")
                if source["noncommercial"] and not allow_nc:
                    raise ValueError("NC source requires explicit --allow-nc")
                if provenance["license"] != source["license"]:
                    raise ValueError("Source license does not match manifest")
                count += 1
        if count != manifest["counts"][kind]:
            raise ValueError(f"Artifact row count mismatch: {kind}")
    attribution = (directory / "ATTRIBUTION.md").read_text()
    admin_engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(admin_engine) as db, db.begin():
            advisory_lock(db, "reference-import")
            existing = db.scalar(
                select(ReferenceBuild).where(ReferenceBuild.digest == build_digest)
            )
            if existing:
                return {"build_id": str(existing.id), "already_imported": True}
            build = ReferenceBuild(digest=build_digest, manifest=manifest, attribution=attribution)
            db.add(build)
            db.flush()
            # Keep source-specific identities. Reimports never change a canonical UUID.
            # New snapshots that change entry IDs remain separate until reviewed alignment.
            entry_map = {}
            for kind in TABLES:
                with (directory / f"{kind}.jsonl").open() as lines:
                    for line in lines:
                        row = json.loads(line)
                        concept_id = None
                        if kind == "entries" and row["entry_type"] == "lemma":
                            identity = digest(
                                ["reference", row["provenance"]["source"], row["entry_id"]]
                            )
                            concept = db.scalar(
                                select(Concept).where(Concept.identity_key == identity)
                            )
                            if concept is None:
                                concept = Concept(
                                    language_tag=row["language"],
                                    owner_user_id=None,
                                    kind="lexeme",
                                    lemma=row["lemma"],
                                    search_key=normalize(row["lemma"]),
                                    pos=row["pos"],
                                    identity_key=identity,
                                    gloss=None,
                                    status="curated",
                                )
                                db.add(concept)
                                db.flush()
                            concept_id = concept.id
                            entry_map[row["entry_id"]] = concept_id
                        elif row.get("entry_id"):
                            concept_id = entry_map.get(row["entry_id"])
                        db.add(
                            ReferenceAssertion(
                                build_id=build.id,
                                assertion_id=row["id"],
                                kind=kind,
                                payload=row,
                                concept_id=concept_id,
                            )
                        )
            return {"build_id": str(build.id), "already_imported": False}
    finally:
        admin_engine.dispose()
