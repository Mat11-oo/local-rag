from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_evaluation_run_manifest_hash"
down_revision = "0008_run_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "evaluation_runs" not in inspector.get_table_names():
        return
    if "manifest_hash" not in {item["name"] for item in inspector.get_columns("evaluation_runs")}:
        op.add_column("evaluation_runs", sa.Column("manifest_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("evaluation_runs", "manifest_hash")
