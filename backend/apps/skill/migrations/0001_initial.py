from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("document", "0005_document_metadata_fields"),
        ("project", "0002_rename_project_own_created_aa3a57_idx_project_pro_owner_i_bc287f_idx"),
        ("repository", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Skill",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("skill_type", models.CharField(choices=[("quick", "Quick"), ("copilot", "Copilot")], default="quick", max_length=20)),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(blank=True, max_length=255, unique=True)),
                ("description", models.TextField(blank=True)),
                ("allowed_contexts", models.JSONField(default=list)),
                ("system_prompt", models.TextField(default="Eres Ecofilia, un asistente especializado en sostenibilidad. Responde siempre basándote en los documentos provistos y cita las fuentes.")),
                ("prompt_template", models.TextField(blank=True)),
                ("model", models.CharField(max_length=100, default="gpt-4o-mini")),
                ("temperature", models.FloatField(default=0.3)),
                ("is_template", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="skills", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("skill_type", "name")},
        ),
        migrations.CreateModel(
            name="SkillStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=255)),
                ("instructions", models.TextField()),
                ("position", models.PositiveIntegerField(default=1)),
                ("skill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="steps", to="skill.skill")),
            ],
            options={"ordering": ("position",), "unique_together": {("skill", "position")}},
        ),
        migrations.CreateModel(
            name="SkillExecution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("extra_instructions", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("running", "Running"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=20)),
                ("output", models.TextField(blank=True)),
                ("output_structured", models.JSONField(blank=True, default=dict)),
                ("document_snapshot", models.JSONField(default=list)),
                ("error_message", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("skill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="executions", to="skill.skill")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="skill_executions", to=settings.AUTH_USER_MODEL)),
                ("repository", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="skill_executions", to="repository.repository")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="skill_executions", to="project.project")),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="skill_executions", to="document.document")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="skill",
            index=models.Index(fields=["owner", "skill_type"], name="skill_skill_owner_type_idx"),
        ),
        migrations.AddIndex(
            model_name="skillexecution",
            index=models.Index(fields=["owner", "created_at"], name="skill_exec_owner_created_idx"),
        ),
        migrations.AddIndex(
            model_name="skillexecution",
            index=models.Index(fields=["skill", "status"], name="skill_exec_skill_status_idx"),
        ),
    ]
