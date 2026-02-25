# Seed ASG Allen Manza evaluation template

import uuid

from django.db import migrations

ASG_TEMPLATE_ID = uuid.UUID("a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d")
PILLAR_IDS = {
    "A": uuid.UUID("a1111111-1111-4111-8111-111111111111"),
    "S": uuid.UUID("b2222222-2222-4222-8222-222222222222"),
    "G": uuid.UUID("c3333333-3333-4333-8333-333333333333"),
    "CF": uuid.UUID("d4444444-4444-4444-8444-444444444444"),
    "RS": uuid.UUID("e5555555-5555-4555-8555-555555555555"),
    "BP": uuid.UUID("f6666666-6666-4666-8666-666666666666"),
}


def seed_asg_template(apps, schema_editor):
    EvaluationTemplate = apps.get_model("evaluation", "EvaluationTemplate")
    EvaluationPillarTemplate = apps.get_model("evaluation", "EvaluationPillarTemplate")
    EvaluationKPITemplate = apps.get_model("evaluation", "EvaluationKPITemplate")

    template, _ = EvaluationTemplate.objects.get_or_create(
        id=ASG_TEMPLATE_ID,
        defaults={
            "name": "ASG Allen Manza",
            "description": "Evaluación de Instituciones Financieras Intermediarias según metodología ASG Allen Manza",
            "methodology": "ASG Allen Manza",
        },
    )

    pillars_data = [
        ("A", "Ambiental", "0.33"),
        ("S", "Social", "0.33"),
        ("G", "Gobernanza", "0.34"),
        ("CF", "Capacidades de financiamiento ASG", "0.25"),
        ("RS", "Transparencia y Reporting", "0.20"),
        ("BP", "Buenas prácticas ASG", "0.20"),
    ]
    for code, name, weight in pillars_data:
        EvaluationPillarTemplate.objects.get_or_create(
            id=PILLAR_IDS[code],
            template=template,
            defaults={"code": code, "name": name, "weight": weight},
        )

    # KPIs for Ambiental (A)
    kpis_a = [
        ("A1", "Cambio climático"),
        ("A2", "Eficiencia de recursos y economía circular"),
        ("A3", "Biodiversidad y ecosistemas"),
    ]
    pillar_a = EvaluationPillarTemplate.objects.get(id=PILLAR_IDS["A"])
    for code, name in kpis_a:
        EvaluationKPITemplate.objects.get_or_create(
            pillar=pillar_a, code=code, defaults={"name": name, "max_score": 3}
        )

    # KPIs for Social (S)
    kpis_s = [
        ("S1", "Empleo y condiciones laborales"),
        ("S2", "Cadena de valor"),
        ("S3", "Comunidades y consumidores"),
    ]
    pillar_s = EvaluationPillarTemplate.objects.get(id=PILLAR_IDS["S"])
    for code, name in kpis_s:
        EvaluationKPITemplate.objects.get_or_create(
            pillar=pillar_s, code=code, defaults={"name": name, "max_score": 3}
        )

    # KPIs for Gobernanza (G)
    kpis_g = [
        ("G1", "Consejo y alta dirección"),
        ("G2", "Gestión de riesgos y estrategia ASG"),
        ("G3", "Ética e integridad"),
    ]
    pillar_g = EvaluationPillarTemplate.objects.get(id=PILLAR_IDS["G"])
    for code, name in kpis_g:
        EvaluationKPITemplate.objects.get_or_create(
            pillar=pillar_g, code=code, defaults={"name": name, "max_score": 3}
        )

    # KPIs for CF, RS, BP (one KPI each)
    for code, name in [("CF", "Capacidades de financiamiento ASG"), ("RS", "Transparencia y Reporting"), ("BP", "Buenas prácticas ASG")]:
        pillar = EvaluationPillarTemplate.objects.get(id=PILLAR_IDS[code])
        EvaluationKPITemplate.objects.get_or_create(
            pillar=pillar, code=code, defaults={"name": name, "max_score": 3}
        )


def reverse_seed(apps, schema_editor):
    EvaluationTemplate = apps.get_model("evaluation", "EvaluationTemplate")
    EvaluationTemplate.objects.filter(id=ASG_TEMPLATE_ID).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("evaluation", "0002_template_evaluation_models"),
    ]

    operations = [
        migrations.RunPython(seed_asg_template, reverse_seed),
    ]
