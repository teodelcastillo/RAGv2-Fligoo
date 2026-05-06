from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0006_skill_default_enabled"),
        ("repository", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="repository",
            name="enabled_skills",
            field=models.ManyToManyField(
                blank=True,
                help_text="Skills/copilots shown in this repository workspace.",
                related_name="enabled_repositories",
                to="skill.skill",
            ),
        ),
    ]
