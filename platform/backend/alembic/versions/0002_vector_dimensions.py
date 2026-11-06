from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "0002_vector_dimensions"
down_revision = "0001_fde_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("knowledge_bases")}
    if "embedding_dimension" not in columns:
        op.add_column("knowledge_bases", sa.Column("embedding_dimension", sa.Integer(), nullable=True))
    if bind.dialect.name == "postgresql":
        op.execute("UPDATE knowledge_bases SET embedding_dimension = (SELECT vector_dims(embedding) FROM document_chunks WHERE document_chunks.knowledge_base_id = knowledge_bases.id AND embedding IS NOT NULL LIMIT 1) WHERE embedding_dimension IS NULL")
        rows = bind.execute(sa.text("SELECT id, embedding_dimension FROM knowledge_bases WHERE embedding_dimension IS NOT NULL")).mappings().all()
        for row in rows:
            dimension = int(row["embedding_dimension"])
            if dimension <= 0:
                continue
            index_name = f"ix_chunks_{row['id'].replace('-', '')}_hnsw"
            op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON document_chunks USING hnsw ((embedding::vector({dimension})) vector_cosine_ops) WHERE knowledge_base_id = '{row['id']}'")
    else:
        rows = bind.execute(sa.text("SELECT id, embedding FROM document_chunks WHERE embedding IS NOT NULL GROUP BY id")).mappings().all()
        for row in rows:
            vector = row["embedding"]
            if isinstance(vector, str):
                vector = json.loads(vector)
            bind.execute(sa.text("UPDATE knowledge_bases SET embedding_dimension = :dimension WHERE id = (SELECT knowledge_base_id FROM document_chunks WHERE id = :chunk_id) AND embedding_dimension IS NULL"), {"dimension": len(vector), "chunk_id": row["id"]})


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        rows = bind.execute(sa.text("SELECT id FROM knowledge_bases")).mappings().all()
        for row in rows:
            op.execute(f"DROP INDEX IF EXISTS ix_chunks_{row['id'].replace('-', '')}_hnsw")
    op.drop_column("knowledge_bases", "embedding_dimension")
