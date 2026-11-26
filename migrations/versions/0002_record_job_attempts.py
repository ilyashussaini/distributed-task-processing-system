"""Record job attempts and index terminal timestamps for monitoring."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_jobs_completed_at", "jobs", ["completed_at"])
    op.create_table(
        "job_attempts",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "number"),
        sa.CheckConstraint("number > 0", name="ck_job_attempts_number"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'abandoned')",
            name="ck_job_attempts_status",
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_job_attempts_duration"),
    )
    op.create_index("ix_job_attempts_started_at", "job_attempts", ["started_at"])


def downgrade() -> None:
    op.drop_table("job_attempts")
    op.drop_index("ix_jobs_completed_at", table_name="jobs")
