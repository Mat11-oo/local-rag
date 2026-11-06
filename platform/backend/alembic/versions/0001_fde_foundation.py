from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db import Base
from app import models

revision = "0001_fde_foundation"
down_revision = None
branch_labels = None
depends_on = None

DEFAULT_WORKSPACE = "00000000-0000-0000-0000-000000000001"
NEW_TABLES = [
    "workspaces",
    "users",
    "memberships",
    "auth_sessions",
    "api_clients",
    "app_versions",
    "evaluation_suites",
    "evaluation_cases",
    "evaluation_runs",
    "feedback",
    "tool_configs",
    "audit_events",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    if "qa_apps" not in tables:
        Base.metadata.create_all(bind)
        return

    additions: dict[str, list[tuple[str, sa.Column]]] = {
        "model_configs": [("workspace_id", sa.Column("workspace_id", sa.String(36), nullable=False, server_default=DEFAULT_WORKSPACE))],
        "knowledge_bases": [("workspace_id", sa.Column("workspace_id", sa.String(36), nullable=False, server_default=DEFAULT_WORKSPACE))],
        "qa_apps": [
            ("workspace_id", sa.Column("workspace_id", sa.String(36), nullable=False, server_default=DEFAULT_WORKSPACE)),
            ("draft_manifest", sa.Column("draft_manifest", sa.JSON(), nullable=False, server_default="{}")),
            ("published_version_id", sa.Column("published_version_id", sa.String(36), nullable=True)),
            ("status", sa.Column("status", sa.String(24), nullable=False, server_default="draft")),
        ],
        "conversations": [
            ("workspace_id", sa.Column("workspace_id", sa.String(36), nullable=False, server_default=DEFAULT_WORKSPACE)),
            ("user_id", sa.Column("user_id", sa.String(36), nullable=True)),
        ],
        "messages": [
            ("simulated", sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false())),
            ("input_values", sa.Column("input_values", sa.JSON(), nullable=False, server_default="{}")),
            ("output_json", sa.Column("output_json", sa.JSON(), nullable=True)),
            ("app_version_id", sa.Column("app_version_id", sa.String(36), nullable=True)),
        ],
        "query_logs": [("workspace_id", sa.Column("workspace_id", sa.String(36), nullable=False, server_default=DEFAULT_WORKSPACE))],
    }
    for table, columns in additions.items():
        existing = {item["name"] for item in inspector.get_columns(table)}
        for name, column in columns:
            if name not in existing:
                op.add_column(table, column)
                if name in {"workspace_id", "user_id", "app_version_id"}:
                    op.create_index(f"ix_{table}_{name}", table, [name], if_not_exists=True)
    missing_tables = [Base.metadata.tables[name] for name in NEW_TABLES if name not in tables]
    if missing_tables:
        Base.metadata.create_all(bind, tables=missing_tables)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.drop_table(table, if_exists=True)
    additions = {
        "model_configs": ["workspace_id"],
        "knowledge_bases": ["workspace_id"],
        "qa_apps": ["workspace_id", "draft_manifest", "published_version_id", "status"],
        "conversations": ["workspace_id", "user_id"],
        "messages": ["simulated", "input_values", "output_json", "app_version_id"],
        "query_logs": ["workspace_id"],
    }
    for table, columns in additions.items():
        for column in columns:
            op.drop_column(table, column)
