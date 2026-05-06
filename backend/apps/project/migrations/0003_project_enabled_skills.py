from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0006_skill_default_enabled"),
        ("project", "0002_rename_project_own_created_aa3a57_idx_project_pro_owner_i_bc287f_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="enabled_skills",
            field=models.ManyToManyField(
                blank=True,
                help_text="Skills/copilots shown in this project workspace.",
                related_name="enabled_projects",
                to="skill.skill",
            ),
        ),
    ]
