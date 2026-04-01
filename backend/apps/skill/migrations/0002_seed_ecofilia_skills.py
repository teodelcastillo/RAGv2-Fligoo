"""
Seed Ecofilia's built-in skill templates.
owner=None marks them as platform-provided (visible to all, non-editable by users).
"""
from django.db import migrations

QUICK_SKILLS = [
    {
        "name": "Document Summary",
        "slug": "ecofilia-document-summary",
        "description": "Generate a concise executive summary of all content in the context.",
        "allowed_contexts": ["repository", "project", "document"],
        "system_prompt": (
            "You are Ecofilia, an expert sustainability analyst. "
            "Produce clear, structured summaries grounded exclusively in the provided documents."
        ),
        "prompt_template": (
            "Analyze the following documents and produce an executive summary.\n\n"
            "The summary must:\n"
            "- Start with a one-paragraph overview of the main topic and scope.\n"
            "- Highlight 3-5 key findings or conclusions.\n"
            "- Note any significant gaps, risks, or limitations mentioned.\n"
            "- Be written in a professional, neutral tone.\n\n"
            "{{extra_instructions}}\n\n"
            "Documents:\n{{context}}"
        ),
        "temperature": 0.3,
    },
    {
        "name": "Key Concepts Glossary",
        "slug": "ecofilia-key-concepts-glossary",
        "description": "Extract and define the most important sustainability terms found across the documents.",
        "allowed_contexts": ["repository", "project", "document"],
        "system_prompt": (
            "You are Ecofilia, a sustainability knowledge expert. "
            "Extract precise definitions from the source documents."
        ),
        "prompt_template": (
            "From the following documents, extract and define the 10 most important "
            "technical or sustainability-related terms.\n\n"
            "Format each entry as:\n"
            "**Term**: Definition (cite document source).\n\n"
            "Sort alphabetically. Only include terms explicitly defined or described in the documents.\n\n"
            "{{extra_instructions}}\n\n"
            "Documents:\n{{context}}"
        ),
        "temperature": 0.2,
    },
    {
        "name": "Compliance Checklist",
        "slug": "ecofilia-compliance-checklist",
        "description": "Identify regulatory requirements and flag potential compliance gaps in the context.",
        "allowed_contexts": ["repository", "project", "document"],
        "system_prompt": (
            "You are Ecofilia, a regulatory compliance specialist. "
            "Analyze documents for compliance obligations and risks."
        ),
        "prompt_template": (
            "Analyze the following documents and produce a compliance checklist.\n\n"
            "For each regulatory requirement or obligation found:\n"
            "- State the requirement clearly.\n"
            "- Indicate whether evidence of compliance is present (Yes / Partial / No / Unclear).\n"
            "- Note the source document and any gaps.\n\n"
            "End with a brief risk summary.\n\n"
            "{{extra_instructions}}\n\n"
            "Documents:\n{{context}}"
        ),
        "temperature": 0.2,
    },
    {
        "name": "Q&A Brief",
        "slug": "ecofilia-qa-brief",
        "description": "Answer a specific question based solely on the documents in the context.",
        "allowed_contexts": ["repository", "project", "document"],
        "system_prompt": (
            "You are Ecofilia, an evidence-based research assistant. "
            "Only use information from the provided documents."
        ),
        "prompt_template": (
            "Using only the documents below, answer the following question as accurately as possible.\n\n"
            "Question: {{extra_instructions}}\n\n"
            "If the documents do not contain enough information to answer, say so explicitly.\n"
            "Always cite the source document for each point.\n\n"
            "Documents:\n{{context}}"
        ),
        "temperature": 0.2,
    },
]

COPILOT_SKILLS = [
    {
        "name": "Project Card",
        "slug": "ecofilia-project-card",
        "description": (
            "Guided copilot that produces a structured project data sheet "
            "based on linked documents."
        ),
        "allowed_contexts": ["project", "repository"],
        "system_prompt": (
            "You are Ecofilia, a sustainability project analyst. "
            "Produce each section based exclusively on the provided documents. "
            "Be factual, concise, and always cite the source."
        ),
        "temperature": 0.3,
        "steps": [
            {
                "position": 1,
                "title": "Project Overview",
                "instructions": (
                    "Write a 2-3 paragraph overview of the project: its purpose, "
                    "sector, geographic scope, and main stakeholders as described in the documents."
                ),
            },
            {
                "position": 2,
                "title": "Objectives & Expected Outcomes",
                "instructions": (
                    "List the main objectives and expected outcomes of the project. "
                    "Use bullet points. Extract only what is explicitly stated in the documents."
                ),
            },
            {
                "position": 3,
                "title": "Environmental & Social Context",
                "instructions": (
                    "Describe the environmental and social context in which this project operates. "
                    "Include relevant indicators, baselines, or conditions mentioned in the documents."
                ),
            },
            {
                "position": 4,
                "title": "Key Risks & Mitigation Measures",
                "instructions": (
                    "Identify the main risks (environmental, social, financial, regulatory) "
                    "mentioned in the documents and describe any mitigation measures proposed."
                ),
            },
            {
                "position": 5,
                "title": "Indicators & Monitoring",
                "instructions": (
                    "List the key performance indicators (KPIs) or monitoring metrics "
                    "mentioned in the documents for tracking project progress."
                ),
            },
        ],
    },
    {
        "name": "Sustainability Report Draft",
        "slug": "ecofilia-sustainability-report",
        "description": (
            "Drafts a sustainability report section by section "
            "following GRI/ESG structure, based on the documents in context."
        ),
        "allowed_contexts": ["project", "repository"],
        "system_prompt": (
            "You are Ecofilia, an expert ESG report writer. "
            "Follow GRI reporting principles: materiality, stakeholder inclusiveness, "
            "sustainability context, and completeness. Cite all sources."
        ),
        "temperature": 0.4,
        "steps": [
            {
                "position": 1,
                "title": "Executive Message",
                "instructions": (
                    "Draft a 2-paragraph executive message for the sustainability report. "
                    "Highlight the organization's main sustainability commitments and achievements "
                    "as evidenced in the documents."
                ),
            },
            {
                "position": 2,
                "title": "Environmental Performance",
                "instructions": (
                    "Summarize the environmental performance section: energy, water, "
                    "emissions (Scope 1/2/3), waste, and biodiversity impact. "
                    "Use data from the documents where available."
                ),
            },
            {
                "position": 3,
                "title": "Social Performance",
                "instructions": (
                    "Summarize social performance: workforce data, health & safety, "
                    "community engagement, and human rights aspects found in the documents."
                ),
            },
            {
                "position": 4,
                "title": "Governance",
                "instructions": (
                    "Describe governance structures, anti-corruption policies, "
                    "and sustainability oversight mechanisms mentioned in the documents."
                ),
            },
            {
                "position": 5,
                "title": "Goals & Commitments",
                "instructions": (
                    "List the explicit sustainability goals, targets, and commitments "
                    "stated in the documents, with timelines if available."
                ),
            },
        ],
    },
    {
        "name": "ESG Risk & Opportunity Map",
        "slug": "ecofilia-esg-risk-map",
        "description": (
            "Analyses documents to produce a structured map of ESG risks and opportunities."
        ),
        "allowed_contexts": ["project", "repository", "document"],
        "system_prompt": (
            "You are Ecofilia, an ESG risk analyst. "
            "Structure risks by Environmental, Social, and Governance categories. "
            "Be specific and cite sources."
        ),
        "temperature": 0.3,
        "steps": [
            {
                "position": 1,
                "title": "Environmental Risks & Opportunities",
                "instructions": (
                    "Identify and describe Environmental risks and opportunities from the documents. "
                    "For each: name, description, likelihood (High/Medium/Low), potential impact, and source."
                ),
            },
            {
                "position": 2,
                "title": "Social Risks & Opportunities",
                "instructions": (
                    "Identify and describe Social risks and opportunities from the documents. "
                    "For each: name, description, likelihood (High/Medium/Low), potential impact, and source."
                ),
            },
            {
                "position": 3,
                "title": "Governance Risks & Opportunities",
                "instructions": (
                    "Identify and describe Governance risks and opportunities from the documents. "
                    "For each: name, description, likelihood (High/Medium/Low), potential impact, and source."
                ),
            },
            {
                "position": 4,
                "title": "Priority Matrix & Recommended Actions",
                "instructions": (
                    "Based on the risks and opportunities identified above, produce a priority matrix "
                    "and recommend 3-5 concrete actions the organization should take."
                ),
            },
        ],
    },
]


def seed_skills(apps, schema_editor):
    Skill = apps.get_model("skill", "Skill")
    SkillStep = apps.get_model("skill", "SkillStep")

    for data in QUICK_SKILLS:
        Skill.objects.get_or_create(
            slug=data["slug"],
            defaults={
                "owner": None,
                "skill_type": "quick",
                "is_template": True,
                "name": data["name"],
                "description": data["description"],
                "allowed_contexts": data["allowed_contexts"],
                "system_prompt": data["system_prompt"],
                "prompt_template": data["prompt_template"],
                "temperature": data["temperature"],
            },
        )

    for raw in COPILOT_SKILLS:
        data = {**raw}
        steps = data.pop("steps", [])
        skill, created = Skill.objects.get_or_create(
            slug=data["slug"],
            defaults={
                "owner": None,
                "skill_type": "copilot",
                "is_template": True,
                "prompt_template": "",
                **{k: v for k, v in data.items() if k != "slug"},
            },
        )
        if created:
            for step in steps:
                SkillStep.objects.create(skill=skill, **step)


def unseed_skills(apps, schema_editor):
    Skill = apps.get_model("skill", "Skill")
    slugs = [s["slug"] for s in QUICK_SKILLS] + [s["slug"] for s in COPILOT_SKILLS]
    Skill.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):
    dependencies = [("skill", "0001_initial")]
    operations = [migrations.RunPython(seed_skills, unseed_skills)]
