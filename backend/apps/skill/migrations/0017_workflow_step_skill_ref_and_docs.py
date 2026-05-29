from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0016_skill_retrieval_query_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="skillstep",
            name="step_type",
            field=models.CharField(
                choices=[
                    ("instruction", "Instruction"),
                    ("skill_ref", "Run existing skill"),
                ],
                default="instruction",
                help_text=(
                    "'instruction' authors from the step's own prompt. 'skill_ref' runs "
                    "an existing quick skill inline and uses its output as this step."
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="skillstep",
            name="linked_skill",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Only for step_type='skill_ref': the quick skill to execute for this "
                    "step. Its prompt/retrieval config is used against this step's documents."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="referenced_in_steps",
                to="skill.skill",
            ),
        ),
        migrations.AddField(
            model_name="skillstep",
            name="document_slugs",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Optional subset of document slugs this step runs against. "
                    "Empty = all documents in the execution context."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="skillstep",
            name="instructions",
            field=models.TextField(
                blank=True,
                help_text="What the AI should produce for this section of the output.",
            ),
        ),
    ]
