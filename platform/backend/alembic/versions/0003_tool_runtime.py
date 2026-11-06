from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_tool_runtime"
down_revision = "0002_vector_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_configs" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns("tool_configs")}
    additions = {
        "secret_encrypted": sa.Column("secret_encrypted", sa.LargeBinary(), nullable=True),
        "connection_status": sa.Column("connection_status", sa.String(24), nullable=False, server_default="untested"),
        "last_tested_at": sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        "last_error": sa.Column("last_error", sa.Text(), nullable=True),
    }
    for name, column in additions.items():
        if name not in existing:
            op.add_column("tool_configs", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_configs" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns("tool_configs")}
    for name in ("last_error", "last_tested_at", "connection_status", "secret_encrypted"):
        if name in existing:
            op.drop_column("tool_configs", name)
