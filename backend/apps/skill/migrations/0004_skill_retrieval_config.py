from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0003_seed_more_skills"),
    ]

    operations = [
        migrations.AddField(
            model_name="skill",
            name="comparative_mode_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, enforce per-document comparative output and use "
                    "hybrid retrieval strategy by default."
                ),
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="k_per_doc",
            field=models.PositiveSmallIntegerField(
                default=2,
                help_text="Candidate chunks to retrieve per document in hybrid mode.",
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="max_per_doc_after_rerank",
            field=models.PositiveSmallIntegerField(
                default=4,
                help_text="Max chunks kept per document after global reranking.",
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="retrieval_strategy",
            field=models.CharField(
                choices=[("global", "Global"), ("hybrid_per_document", "Hybrid Per Document")],
                default="global",
                help_text="Chunk retrieval strategy to build model context.",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="strict_missing_evidence",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When comparative mode is enabled, require explicit 'no evidence' "
                    "statements for missing document/criterion pairs."
                ),
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="total_limit",
            field=models.PositiveSmallIntegerField(
                default=12,
                help_text="Maximum number of chunks included in the final merged context.",
            ),
        ),
    ]
