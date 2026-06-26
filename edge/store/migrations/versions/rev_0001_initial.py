"""S1 initial: contract-derived tables + least-privilege roles + insert-only audit guards.

Revision ID: 0001
Create Date: Run S1

- Tables/indexes/sequence are created from the contract-derived ``schema.metadata`` (NOTE F8) — no
  hand-written DDL for the contract entities.
- Least-privilege roles + grants (NOTE prod-bar b): ``eunomia_writer`` (consoles — insert/update +
  allocate), ``eunomia_reader`` (ingest / god's-view — select-only), ``eunomia_admin`` (DDL). NOLOGIN
  group roles; nothing connects as superuser.
- The audit tables (the event log, the camera_id ledger, the import-backup table) are INSERT-ONLY
  (NOTE prod-bar c): no UPDATE/DELETE grant AND a ``BEFORE UPDATE OR DELETE`` trigger that RAISES.
"""

from __future__ import annotations

from alembic import op

from eunomia_edge_store import schema

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

WRITER = "eunomia_writer"
READER = "eunomia_reader"
ADMIN = "eunomia_admin"
ROLES = (WRITER, READER, ADMIN)


def upgrade() -> None:
    bind = op.get_bind()
    schema.metadata.create_all(bind)
    _create_roles()
    _grants()
    _audit_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    _drop_audit_triggers()
    schema.metadata.drop_all(bind)
    _drop_roles()


def _create_roles() -> None:
    # Idempotent: NOLOGIN group roles a deploy GRANTs to real login users (no superuser path).
    checks = "\n".join(
        f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{r}') THEN "
        f"CREATE ROLE {r} NOLOGIN; END IF;"
        for r in ROLES
    )
    op.execute(f"DO $$\nBEGIN\n{checks}\nEND $$;")


def _grants() -> None:
    op.execute(f"GRANT USAGE ON SCHEMA public TO {WRITER}, {READER}, {ADMIN};")
    # reader: select-only across everything.
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READER};")
    # admin: full DDL/DML.
    op.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {ADMIN};")
    op.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {ADMIN};")
    # writer: insert/update on current-state tables (no DELETE — the contract voids by flag).
    for table in schema.CURRENT_STATE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {WRITER};")
    # writer on the audit tables: INSERT + SELECT only — no UPDATE/DELETE (insert-only, prod-bar c).
    for table in schema.AUDIT_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {WRITER};")
    # writer needs the sequences (camera_id_seq + the identity sequences) to insert/allocate.
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {WRITER};")


def _audit_triggers() -> None:
    # No `%` format specifiers in the message — avoids the psycopg paramstyle footgun on op.execute.
    op.execute(
        "CREATE OR REPLACE FUNCTION eunomia_forbid_mutation() RETURNS trigger AS $$\n"
        "BEGIN\n"
        "  RAISE EXCEPTION 'append-only audit table: UPDATE/DELETE is forbidden "
        "(insert-only, NOTE prod-bar c)';\n"
        "END;\n"
        "$$ LANGUAGE plpgsql;"
    )
    for table in schema.AUDIT_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION eunomia_forbid_mutation();"
        )


def _drop_audit_triggers() -> None:
    for table in schema.AUDIT_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table};")
    op.execute("DROP FUNCTION IF EXISTS eunomia_forbid_mutation();")


def _drop_roles() -> None:
    for role in ROLES:
        # Revoke grants first so the role is droppable; guarded so a shared role won't fail downgrade.
        op.execute(
            f"DO $$\nBEGIN\n"
            f"  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN\n"
            f"    EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}';\n"
            f"    EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}';\n"
            f"    EXECUTE 'REVOKE ALL ON SCHEMA public FROM {role}';\n"
            f"    DROP ROLE {role};\n"
            f"  END IF;\nEND $$;"
        )
