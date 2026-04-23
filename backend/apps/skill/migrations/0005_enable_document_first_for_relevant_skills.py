from django.db import migrations


MULTI_DOCUMENT_CONTEXTS = {"repository", "project"}
DOCUMENT_FIRST_KEYWORDS = (
    "compar",
    "versus",
    "vs ",
    "benchmark",
    "checklist",
    "extract",
    "snapshot",
    "map",
    "diagnosis",
    "table",
    "matriz",
    "criter",
)


def _requires_document_first_analysis(skill) -> bool:
    allowed_contexts = skill.allowed_contexts or []
    has_multi_document_scope = bool(set(allowed_contexts).intersection(MULTI_DOCUMENT_CONTEXTS))
    if not has_multi_document_scope:
        return False
    if skill.skill_type == "copilot":
        return True
    text = f"{skill.name} {skill.description} {skill.prompt_template}".lower()
    return any(keyword in text for keyword in DOCUMENT_FIRST_KEYWORDS)


def forwards(apps, schema_editor):
    Skill = apps.get_model("skill", "Skill")
    for skill in Skill.objects.all():
        if not _requires_document_first_analysis(skill):
            continue
        skill.comparative_mode_enabled = True
        skill.retrieval_strategy = "hybrid_per_document"
        if not skill.strict_missing_evidence:
            skill.strict_missing_evidence = True
        skill.save(
            update_fields=[
                "comparative_mode_enabled",
                "retrieval_strategy",
                "strict_missing_evidence",
            ]
        )


def backwards(apps, schema_editor):
    # Keep current values when rolling back to avoid unsafe data loss.
    return


class Migration(migrations.Migration):
    dependencies = [("skill", "0004_skill_retrieval_config")]
    operations = [migrations.RunPython(forwards, backwards)]
