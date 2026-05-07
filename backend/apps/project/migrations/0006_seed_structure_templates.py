from django.db import migrations


TEMPLATES = [
    {
        "name": "Inventario de GEI",
        "slug": "inventario-gei",
        "description": (
            "Estructura para la elaboracion de un inventario de gases de efecto "
            "invernadero siguiendo el GHG Protocol Corporate Standard."
        ),
        "sections": [
            {
                "position": 1,
                "title": "Definicion de Alcance Organizacional",
                "description": (
                    "Establecer los limites organizacionales del inventario: "
                    "enfoque de control operacional o financiero, entidades incluidas."
                ),
            },
            {
                "position": 2,
                "title": "Definicion de Alcance Operacional",
                "description": (
                    "Identificar las fuentes de emision por Scope 1, 2 y 3 "
                    "aplicables a la organizacion."
                ),
            },
            {
                "position": 3,
                "title": "Recopilacion de Datos de Actividad",
                "description": (
                    "Recopilar datos de consumo: energia electrica, combustibles, "
                    "transporte, residuos, viajes de negocio, etc."
                ),
            },
            {
                "position": 4,
                "title": "Seleccion de Factores de Emision",
                "description": (
                    "Identificar y documentar los factores de emision apropiados "
                    "para cada fuente (IPCC, IEA, factores nacionales)."
                ),
            },
            {
                "position": 5,
                "title": "Calculo de Emisiones",
                "description": (
                    "Calcular las emisiones de GEI por fuente y scope en tCO2e. "
                    "Documentar la metodologia de calculo."
                ),
            },
            {
                "position": 6,
                "title": "Analisis de Incertidumbre y Calidad",
                "description": (
                    "Evaluar la calidad de los datos, identificar brechas y "
                    "documentar supuestos y limitaciones."
                ),
            },
            {
                "position": 7,
                "title": "Reporte Final",
                "description": (
                    "Compilar el inventario en formato de reporte: resumen ejecutivo, "
                    "metodologia, resultados por scope, conclusiones y recomendaciones."
                ),
            },
        ],
    },
    {
        "name": "Evaluacion de Materialidad ESG",
        "slug": "evaluacion-materialidad-esg",
        "description": (
            "Estructura para conducir una evaluacion de materialidad de temas "
            "ESG siguiendo las mejores practicas (GRI, ISSB, doble materialidad)."
        ),
        "sections": [
            {
                "position": 1,
                "title": "Identificacion de Temas ESG",
                "description": (
                    "Listar los temas ambientales, sociales y de gobernanza "
                    "potencialmente relevantes para la organizacion y su sector."
                ),
            },
            {
                "position": 2,
                "title": "Mapeo de Stakeholders",
                "description": (
                    "Identificar los grupos de interes clave y sus expectativas "
                    "respecto a temas de sostenibilidad."
                ),
            },
            {
                "position": 3,
                "title": "Evaluacion de Impacto",
                "description": (
                    "Evaluar el impacto de cada tema ESG sobre la organizacion "
                    "(materialidad financiera) y sobre el entorno (materialidad de impacto)."
                ),
            },
            {
                "position": 4,
                "title": "Priorizacion y Matriz de Materialidad",
                "description": (
                    "Priorizar los temas ESG y construir la matriz de materialidad "
                    "con los resultados de la evaluacion."
                ),
            },
            {
                "position": 5,
                "title": "Validacion con Stakeholders",
                "description": (
                    "Validar los resultados con los grupos de interes clave "
                    "y la alta direccion."
                ),
            },
            {
                "position": 6,
                "title": "Plan de Accion y Reporte",
                "description": (
                    "Definir acciones prioritarias para los temas materiales "
                    "y compilar el reporte de materialidad."
                ),
            },
        ],
    },
    {
        "name": "Reporte de Sostenibilidad GRI",
        "slug": "reporte-sostenibilidad-gri",
        "description": (
            "Estructura para elaborar un reporte de sostenibilidad siguiendo "
            "los GRI Universal Standards 2021."
        ),
        "sections": [
            {
                "position": 1,
                "title": "Perfil de la Organizacion",
                "description": (
                    "Describir la organizacion: actividades, mercados, tamano, "
                    "cadena de valor, gobernanza."
                ),
            },
            {
                "position": 2,
                "title": "Estrategia y Analisis",
                "description": (
                    "Declaracion del CEO/directivo sobre sostenibilidad, "
                    "principales impactos, riesgos y oportunidades."
                ),
            },
            {
                "position": 3,
                "title": "Materialidad y Participacion de Stakeholders",
                "description": (
                    "Descripcion del proceso de materialidad y como se "
                    "involucraron los grupos de interes."
                ),
            },
            {
                "position": 4,
                "title": "Indicadores Ambientales",
                "description": (
                    "Contenidos sobre energia, agua, emisiones, residuos, "
                    "biodiversidad y cumplimiento ambiental."
                ),
            },
            {
                "position": 5,
                "title": "Indicadores Sociales",
                "description": (
                    "Contenidos sobre empleo, salud y seguridad, formacion, "
                    "diversidad, derechos humanos, comunidades."
                ),
            },
            {
                "position": 6,
                "title": "Indicadores de Gobernanza",
                "description": (
                    "Contenidos sobre etica, anticorrupcion, politicas publicas, "
                    "cumplimiento normativo."
                ),
            },
            {
                "position": 7,
                "title": "Indice GRI y Verificacion",
                "description": (
                    "Compilar el indice de contenidos GRI y gestionar "
                    "la verificacion externa si aplica."
                ),
            },
        ],
    },
]


def seed_templates(apps, schema_editor):
    Template = apps.get_model("project", "ProjectStructureTemplate")
    Section = apps.get_model("project", "ProjectStructureSection")

    for tmpl_data in TEMPLATES:
        template, _ = Template.objects.get_or_create(
            slug=tmpl_data["slug"],
            defaults={
                "name": tmpl_data["name"],
                "description": tmpl_data["description"],
            },
        )
        for sec_data in tmpl_data["sections"]:
            Section.objects.get_or_create(
                template=template,
                position=sec_data["position"],
                defaults={
                    "title": sec_data["title"],
                    "description": sec_data["description"],
                },
            )


def unseed_templates(apps, schema_editor):
    Template = apps.get_model("project", "ProjectStructureTemplate")
    slugs = [t["slug"] for t in TEMPLATES]
    Template.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0005_sprint5_copilot_structure"),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
