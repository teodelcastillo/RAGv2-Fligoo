"""
Add HNSW approximate nearest-neighbor index on smart_chunks.embedding.

Why HNSW over IVFFlat:
- No training required (IVFFlat needs VACUUM/ANALYZE before it's useful).
- Supports incremental inserts without re-training — important for a live library
  where documents are uploaded continuously.
- Query performance: O(log N) in the number of indexed vectors.
- The index is used when the query optimizer selects a vector-distance ORDER BY
  without a highly selective WHERE clause — i.e., the library-wide global search.

Parameters:
- m=16:             number of bi-directional links per node (sweet spot for
                    recall/build-time tradeoff at this scale).
- ef_construction=64: search depth during index build; higher = better recall
                    at the cost of slower build. 64 is the default and fine
                    for < 10M vectors.

The index is created CONCURRENTLY so production table access is not blocked
during the migration. Django migrations do not support CONCURRENTLY natively,
so we use RunSQL with a state_operations no-op to keep the migration graph
consistent.
"""
from django.db import migrations


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("document", "0010_remove_document_doc_doc_category_ref_id_idx_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS
                    smart_chunks_embedding_hnsw_idx
                ON document_smartchunk
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """,
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS smart_chunks_embedding_hnsw_idx;",
        ),
    ]
