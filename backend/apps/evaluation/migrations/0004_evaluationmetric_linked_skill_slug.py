from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("evaluation", "0003_seed_asg_allen_manza_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationmetric",
            name="linked_skill_slug",
            field=models.SlugField(
                blank=True,
                help_text="Optional skill to pre-populate this metric's response.",
                null=True,
            ),
        ),
    ]
