from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0006_seed_structure_templates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="projectstructuretemplate",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                help_text="Owner of the template. Null means global template.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="project_structure_templates",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

