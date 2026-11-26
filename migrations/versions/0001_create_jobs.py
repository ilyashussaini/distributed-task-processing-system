"""Create the jobs table and scheduling indexes."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("dispatch_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')", name="ck_jobs_status"
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts", name="ck_jobs_attempts"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_created_at_id", "jobs", ["created_at", "id"])
    op.create_index("ix_jobs_status_dispatch_after", "jobs", ["status", "dispatch_after"])
    op.create_index("ix_jobs_status_lease_expires_at", "jobs", ["status", "lease_expires_at"])


def downgrade() -> None:
    op.drop_table("jobs")
