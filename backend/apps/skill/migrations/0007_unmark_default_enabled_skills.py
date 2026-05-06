from django.db import migrations


def unmark_default_enabled_skills(apps, schema_editor):
    Skill = apps.get_model("skill", "Skill")
    Skill.objects.filter(is_default_enabled=True).update(is_default_enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0006_skill_default_enabled"),
    ]

    operations = [
        migrations.RunPython(unmark_default_enabled_skills, migrations.RunPython.noop),
    ]
