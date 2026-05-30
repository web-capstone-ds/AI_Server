"""replace recipe_id with recipe_hash

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31 02:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lot_embeddings_recipe")
    op.execute("""
        ALTER TABLE lot_embeddings
        RENAME COLUMN recipe_id TO recipe_hash
    """)
    op.execute("""
        UPDATE lot_embeddings
        SET recipe_hash = 'legacy_recipe_hash_redacted'
        WHERE recipe_hash !~ '^[0-9a-f]{64}$'
    """)
    op.execute("""
        UPDATE lot_embeddings
        SET chunk_text = regexp_replace(chunk_text, 'recipe=[^ |]+', 'recipe_hash=legacy_recipe', 'g')
        WHERE chunk_text LIKE '%recipe=%'
    """)
    op.execute("""
        UPDATE ingest_batches
        SET payload_raw = jsonb_set(
            payload_raw,
            '{lotSummary}'::text[],
            (
                ((payload_raw -> ('lotSummary'::text)) - ('recipe_id'::text))
                || jsonb_build_object('recipeHash', 'legacy_recipe_hash_redacted')
            )
        )
        WHERE (payload_raw -> ('lotSummary'::text)) ? ('recipe_id'::text)
    """)
    op.execute("""
        UPDATE ingest_batches
        SET payload_raw = jsonb_set(
            payload_raw,
            '{records}'::text[],
            COALESCE((
                SELECT jsonb_agg(
                    CASE
                        WHEN record ? 'recipe_id'::text
                        THEN (record - 'recipe_id'::text) || jsonb_build_object('recipeHash', 'legacy_recipe_hash_redacted')
                        ELSE record
                    END
                )
                FROM jsonb_array_elements(payload_raw -> ('records'::text)) AS record
            ), '[]'::jsonb)
        )
        WHERE payload_raw ? 'records'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_lot_embeddings_recipe_hash
        ON lot_embeddings (recipe_hash, dispatched_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lot_embeddings_recipe_hash")
    op.execute("""
        ALTER TABLE lot_embeddings
        RENAME COLUMN recipe_hash TO recipe_id
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_lot_embeddings_recipe
        ON lot_embeddings (recipe_id, dispatched_at DESC)
    """)
