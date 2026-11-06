from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_app_version_notes"
down_revision = "0004_file_chunk_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_versions" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns("app_versions")}
    if "release_notes" not in existing:
        op.add_column("app_versions", sa.Column("release_notes", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_versions" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns("app_versions")}
    if "release_notes" in existing:
        op.drop_column("app_versions", "release_notes")
