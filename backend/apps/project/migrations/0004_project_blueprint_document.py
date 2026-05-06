from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0005_document_metadata_fields"),
        ("project", "0003_project_enabled_skills"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="blueprint_document",
            field=models.ForeignKey(
                blank=True,
                help_text="Documento fuente central del proyecto (blueprint).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="blueprint_for_projects",
                to="document.document",
            ),
        ),
    ]
