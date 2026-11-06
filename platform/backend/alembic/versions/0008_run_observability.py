from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_run_observability"
down_revision = "0007_evaluation_case_return"
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column("app_version_id", sa.String(36), nullable=True),
    sa.Column("channel", sa.String(24), nullable=False, server_default="web"),
    sa.Column("model_id", sa.String(36), nullable=True),
    sa.Column("model_name", sa.String(180), nullable=True),
    sa.Column("cost", sa.Float(), nullable=True),
    sa.Column("message_id", sa.String(36), nullable=True),
    sa.Column("run_metadata", sa.JSON(), nullable=False, server_default="{}"),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "query_logs" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns("query_logs")}
    for column in COLUMNS:
        if column.name not in existing:
            op.add_column("query_logs", column.copy())
    indexes = {item["name"] for item in inspector.get_indexes("query_logs")}
    if "ix_query_logs_channel" not in indexes:
        op.create_index("ix_query_logs_channel", "query_logs", ["channel"])
    if "ix_query_logs_message_id" not in indexes:
        op.create_index("ix_query_logs_message_id", "query_logs", ["message_id"])
    if "ix_query_logs_started_at" not in indexes:
        op.create_index("ix_query_logs_started_at", "query_logs", ["started_at"])


def downgrade() -> None:
    for name in ("ix_query_logs_started_at", "ix_query_logs_message_id", "ix_query_logs_channel"):
        op.drop_index(name, table_name="query_logs")
    for column in reversed(COLUMNS):
        op.drop_column("query_logs", column.name)
