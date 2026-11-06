from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_evaluation_case_return"
down_revision = "0006_app_shares"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "evaluation_suites" not in tables or "evaluation_cases" not in tables:
        return

    suite_columns = _column_names(inspector, "evaluation_suites")
    if "description" not in suite_columns:
        op.add_column("evaluation_suites", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    if "is_release_gate" not in suite_columns:
        op.add_column("evaluation_suites", sa.Column("is_release_gate", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "created_by" not in suite_columns:
        op.add_column("evaluation_suites", sa.Column("created_by", sa.String(36), nullable=True))

    case_columns = _column_names(inspector, "evaluation_cases")
    source_log_column = (
        sa.Column("source_log_id", sa.String(36), nullable=True)
        if bind.dialect.name == "sqlite"
        else sa.Column(
            "source_log_id",
            sa.String(36),
            sa.ForeignKey("query_logs.id", ondelete="SET NULL"),
            nullable=True,
        )
    )
    additions = [
        ("case_type", sa.Column("case_type", sa.String(16), nullable=False, server_default="manual")),
        ("readiness", sa.Column("readiness", sa.String(24), nullable=False, server_default="ready")),
        ("actual_output", sa.Column("actual_output", sa.Text(), nullable=False, server_default="")),
        ("expected_output", sa.Column("expected_output", sa.Text(), nullable=False, server_default="")),
        ("tags", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]")),
        ("source_log_id", source_log_column),
        ("source_trace_id", sa.Column("source_trace_id", sa.String(36), nullable=True)),
        ("source_conversation_id", sa.Column("source_conversation_id", sa.String(36), nullable=True)),
        ("source_snapshot", sa.Column("source_snapshot", sa.JSON(), nullable=False, server_default="{}")),
        ("created_by", sa.Column("created_by", sa.String(36), nullable=True)),
    ]
    for name, column in additions:
        if name not in case_columns:
            op.add_column("evaluation_cases", column)

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("evaluation_cases")}
    if "ix_evaluation_cases_case_type" not in indexes:
        op.create_index("ix_evaluation_cases_case_type", "evaluation_cases", ["case_type"])
    if "ix_evaluation_cases_readiness" not in indexes:
        op.create_index("ix_evaluation_cases_readiness", "evaluation_cases", ["readiness"])
    if "ix_evaluation_cases_source_log_id" not in indexes:
        op.create_index("ix_evaluation_cases_source_log_id", "evaluation_cases", ["source_log_id"])
    if "ix_evaluation_cases_source_trace_id" not in indexes:
        op.create_index("ix_evaluation_cases_source_trace_id", "evaluation_cases", ["source_trace_id"])
    if "uq_evaluation_case_suite_source_trace" not in indexes:
        op.create_index(
            "uq_evaluation_case_suite_source_trace",
            "evaluation_cases",
            ["suite_id", "source_trace_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "evaluation_cases" in inspector.get_table_names():
        indexes = {item["name"] for item in inspector.get_indexes("evaluation_cases")}
        for name in [
            "uq_evaluation_case_suite_source_trace",
            "ix_evaluation_cases_source_trace_id",
            "ix_evaluation_cases_source_log_id",
            "ix_evaluation_cases_readiness",
            "ix_evaluation_cases_case_type",
        ]:
            if name in indexes:
                op.drop_index(name, table_name="evaluation_cases")
        columns = _column_names(sa.inspect(bind), "evaluation_cases")
        for name in [
            "created_by",
            "source_snapshot",
            "source_conversation_id",
            "source_trace_id",
            "source_log_id",
            "tags",
            "expected_output",
            "actual_output",
            "readiness",
            "case_type",
        ]:
            if name in columns:
                op.drop_column("evaluation_cases", name)
    if "evaluation_suites" in sa.inspect(bind).get_table_names():
        columns = _column_names(sa.inspect(bind), "evaluation_suites")
        for name in ["created_by", "is_release_gate", "description"]:
            if name in columns:
                op.drop_column("evaluation_suites", name)
