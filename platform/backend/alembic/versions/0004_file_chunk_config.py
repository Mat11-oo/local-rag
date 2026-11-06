from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_file_chunk_config"
down_revision = "0003_tool_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_files" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns("knowledge_files")}
    if "chunk_config" not in existing:
        op.add_column(
            "knowledge_files",
            sa.Column("chunk_config", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_files" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns("knowledge_files")}
    if "chunk_config" in existing:
        op.drop_column("knowledge_files", "chunk_config")
