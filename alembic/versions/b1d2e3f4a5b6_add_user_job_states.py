"""add user_job_states table

Revision ID: b1d2e3f4a5b6
Revises: a0cbfadf5077
Create Date: 2026-04-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b1d2e3f4a5b6"
down_revision = "a0cbfadf5077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_job_states",
        sa.Column("user_id", sa.String(30), nullable=False),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("score_details", postgresql.JSONB(), nullable=True),
        sa.Column("tier", sa.String(1), nullable=True),
        sa.Column("status", sa.String(30), server_default="new", nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposal_draft", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "candidate_id"),
    )
    op.create_index("ix_ujs_user_status", "user_job_states", ["user_id", "status"])
    op.create_index("ix_ujs_user_score", "user_job_states", ["user_id", "score"])
    op.create_index("ix_ujs_user_notified", "user_job_states", ["user_id", "notified_at"])


def downgrade() -> None:
    op.drop_index("ix_ujs_user_notified", table_name="user_job_states")
    op.drop_index("ix_ujs_user_score", table_name="user_job_states")
    op.drop_index("ix_ujs_user_status", table_name="user_job_states")
    op.drop_table("user_job_states")
