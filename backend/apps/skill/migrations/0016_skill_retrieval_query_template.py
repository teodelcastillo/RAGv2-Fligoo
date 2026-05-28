from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0015_rename_skill_skill_owner_type_idx_skill_skill_owner_i_0d5f3f_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="skill",
            name="retrieval_query_template",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Optional explicit retrieval query. When set, used instead of the "
                    "auto-built query from name+description. Supports {{extra_instructions}} placeholder."
                ),
            ),
        ),
    ]
