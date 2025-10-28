# apps/document/migrations/00xx_search_indexes.py
from django.db import migrations

SQL = r"""
-- 1) Extensions (idempotent)
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- create an immutable wrapper that hard-codes the dictionary name
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT public.unaccent('public.unaccent', $1)
$$;

-- 2) Normalized content (stored/generated column)
ALTER TABLE document_smartchunk
  ADD COLUMN IF NOT EXISTS content_norm text
  GENERATED ALWAYS AS (immutable_unaccent(lower(content))) STORED;
  

-- 3) Trigram index on normalized text
CREATE INDEX IF NOT EXISTS document_smartchunk_content_norm_trgm
  ON document_smartchunk
  USING gin (content_norm gin_trgm_ops);

-- 4) Numeric tokens array
ALTER TABLE document_smartchunk
  ADD COLUMN IF NOT EXISTS num_tokens bigint[];

-- 5) GIN index on numeric tokens
CREATE INDEX IF NOT EXISTS smartchunk_num_tokens_gin
  ON document_smartchunk
  USING gin (num_tokens);

-- 6) Speed up common filters
CREATE INDEX IF NOT EXISTS smartchunk_document_id_idx
  ON document_smartchunk(document_id);

-- 7) Vector ANN index (pgvector required; cosine is common)
-- If you prefer IVFFLAT, replace with ivfflat and tune lists/probes.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = ANY (current_schemas(true))
      AND indexname = 'smartchunk_embedding_hnsw'
  ) THEN
    CREATE INDEX smartchunk_embedding_hnsw
      ON document_smartchunk
      USING hnsw (embedding vector_cosine_ops)
      WITH (m = 16, ef_construction = 200);
  END IF;
END$$;
"""

class Migration(migrations.Migration):
    dependencies = [
        ("document", "0002_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL),
    ]
