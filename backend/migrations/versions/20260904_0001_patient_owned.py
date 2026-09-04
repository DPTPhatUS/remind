"""Single-migration patient-owned refactor.

Lossy downgrade: ``*_by_user_id`` columns are not recreated (FK targets no
longer exist); opted-out people are permanently deleted (their right to be
hidden is preserved by removal, not by status). Multi-worker startup
(gunicorn -w N) may insert transient duplicate Patient rows; see lifespan-hook
assumption in .omo/drafts/patient-owned-remind.md.

Revision ID: 20260904_0001
Revises: 20260616_0001
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0001"
down_revision: str | None = "20260616_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- (1)-(5) drop caregiver/user-tracking columns ----
    # Plain String(36), no FK constraints, no inter-column drop ordering.
    # IF EXISTS guards the upgrade round-trip against a lossy downgrade
    # that omitted these columns (see module docstring).
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS actor_user_id")
    op.execute("ALTER TABLE consent_records DROP COLUMN IF EXISTS recorded_by_user_id")
    op.execute("ALTER TABLE memory_claims DROP COLUMN IF EXISTS confirmed_by_user_id")
    op.execute("ALTER TABLE relationships DROP COLUMN IF EXISTS confirmed_by_user_id")
    op.execute("ALTER TABLE corrections DROP COLUMN IF EXISTS corrected_by_user_id")

    # ---- (6)-(11) drop tables in FK-safe order ----
    # consent_records.person_id FK -> people.id (entities.py:67) -> dropped at (6)
    # caregiver_access.user_id FK -> user_accounts.id (entities.py:31)
    #   -> caregiver_access MUST be dropped before user_accounts
    op.drop_table("consent_records")    # (6)
    op.drop_table("audit_logs")          # (7)
    op.drop_table("corrections")         # (8)
    op.drop_table("review_items")        # (9)
    op.drop_table("caregiver_access")    # (10)
    op.drop_table("user_accounts")       # (11)

    # ---- (12) drop people.sensitive ----
    op.drop_column("people", "sensitive")

    # ---- (13) data normalization ----
    # Rename legacy recognition_status values to canonical names, then
    # permanently delete opted-out people (right-to-be-forgotten semantics).
    op.execute(
        "UPDATE people SET recognition_status='recognized' "
        "WHERE recognition_status='seen_before'"
    )
    op.execute(
        "UPDATE people SET recognition_status='confirmed' "
        "WHERE recognition_status='trusted'"
    )
    op.execute(
        "DELETE FROM people "
        "WHERE recognition_status='opted_out' OR consent_status='opted_out'"
    )


def downgrade() -> None:
    # Recreate people.sensitive before anything that might reference it
    # (none currently do, but keep order consistent with initial schema).
    op.add_column(
        "people",
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # ---- lossy shell tables (no `*_by_user_id` columns) ----
    # user_accounts is recreated as a shell so that *no* downgrade ever
    # points a column FK at it (the column would be orphan anyway).
    op.create_table(
        "user_accounts",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_user_accounts_email", "user_accounts", ["email"])

    op.create_table(
        "audit_logs",
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "caregiver_access",
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("access_level", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "consent_records",
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("consent_status", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=160), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consent_records_person_id", "consent_records", ["person_id"])

    op.create_table(
        "review_items",
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_items_patient_id", "review_items", ["patient_id"])
    op.create_index("ix_review_items_status", "review_items", ["status"])

    op.create_table(
        "corrections",
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("correction_type", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Note: ``actor_user_id`` / ``confirmed_by_user_id`` / ``recorded_by_user_id``
    # columns are intentionally NOT recreated on the shell tables; their
    # FK targets no longer exist after this refactor and reintroducing them
    # would force an immediate second lossy downgrade to drop them again.