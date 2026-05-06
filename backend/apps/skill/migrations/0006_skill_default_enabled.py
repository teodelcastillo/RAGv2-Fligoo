from django.db import migrations, models


def mark_default_skills(apps, schema_editor):
    Skill = apps.get_model("skill", "Skill")
    Skill.objects.filter(slug__in=["ecofilia-document-summary"]).update(
        is_default_enabled=True
    )


def unmark_default_skills(apps, schema_editor):
    Skill = apps.get_model("skill", "Skill")
    Skill.objects.filter(slug__in=["ecofilia-document-summary"]).update(
        is_default_enabled=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0005_enable_document_first_for_relevant_skills"),
    ]

    operations = [
        migrations.AddField(
            model_name="skill",
            name="is_default_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When true, this skill is enabled by default in every repository/project "
                    "workspace unless the user adds more plugins."
                ),
            ),
        ),
        migrations.RunPython(mark_default_skills, unmark_default_skills),
    ]
