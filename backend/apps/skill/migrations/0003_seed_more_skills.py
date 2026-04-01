"""
Additional Ecofilia skill templates — batch 2.
"""
from django.db import migrations

QUICK_SKILLS = [
    {
        "name": "GHG Emissions Snapshot",
        "slug": "ecofilia-ghg-emissions-snapshot",
        "description": (
            "Extracts all greenhouse gas emissions data (Scope 1, 2, 3), "
            "baselines, and reduction targets from documents into a structured table."
        ),
        "allowed_contexts": ["repository", "project", "document"],
        "system_prompt": (
            "You are Ecofilia, an expert in greenhouse gas accounting and climate reporting. "
            "Extract only quantitative data that is explicitly stated in the documents."
        ),
        "prompt_template": (
            "Analyze the following documents and produce a structured GHG emissions snapshot.\n\n"
            "Output format:\n"
            "1. **Emissions Summary Table** — For each scope found (Scope 1, 2, 3), provide:\n"
            "   - Scope | Amount (tCO2e) | Year | Source document\n\n"
            "2. **Baseline & Targets** — List any stated emissions baselines and reduction targets "
            "(e.g. '30% reduction vs 2020 baseline by 2030').\n\n"
            "3. **Data Gaps** — Note any scopes or years for which data was not found.\n\n"
            "If no emissions data is present in the documents, state this clearly.\n\n"
            "{{extra_instructions}}\n\n"
            "Documents:\n{{context}}"
        ),
        "temperature": 0.2,
    },
    {
        "name": "Action Plan Extractor",
        "slug": "ecofilia-action-plan-extractor",
        "description": (
            "Identifies and lists all explicit commitments, action items, "
            "and next steps mentioned across the documents."
        ),
        "allowed_contexts": ["repository", "project", "document"],
        "system_prompt": (
            "You are Ecofilia, a sustainability project manager. "
            "Extract only concrete, actionable items — not aspirations or vague statements."
        ),
        "prompt_template": (
            "From the following documents, extract all explicit action items, commitments, "
            "and next steps.\n\n"
            "For each item:\n"
            "- **Action**: What needs to be done (specific and concrete).\n"
            "- **Owner**: Responsible party if mentioned.\n"
            "- **Deadline**: Timeline or due date if stated.\n"
            "- **Source**: Document where this was found.\n\n"
            "Group actions by theme (e.g. Environmental, Social, Governance, Operational).\n"
            "Exclude vague statements like 'we will strive to improve'. "
            "Include only items with a clear deliverable.\n\n"
            "{{extra_instructions}}\n\n"
            "Documents:\n{{context}}"
        ),
        "temperature": 0.2,
    },
]

COPILOT_SKILLS = [
    {
        "name": "Sustainability Diagnosis",
        "slug": "ecofilia-sustainability-diagnosis",
        "description": (
            "4-step copilot that produces a full sustainability diagnosis: "
            "current state, gaps, recommendations, and implementation roadmap."
        ),
        "allowed_contexts": ["project", "repository"],
        "system_prompt": (
            "You are Ecofilia, a senior sustainability consultant. "
            "Build each section on the evidence in the provided documents. "
            "Be specific, cite sources, and avoid generic advice."
        ),
        "temperature": 0.4,
        "steps": [
            {
                "position": 1,
                "title": "Current State Assessment",
                "instructions": (
                    "Describe the organization's or project's current sustainability performance "
                    "based strictly on the provided documents. Cover environmental, social, and "
                    "governance dimensions. Use data and evidence where available. "
                    "Be factual — do not infer beyond what is stated."
                ),
            },
            {
                "position": 2,
                "title": "Gap Analysis",
                "instructions": (
                    "Based on the current state described above, identify the main gaps between "
                    "current performance and sustainability best practices or the organization's "
                    "own stated goals. For each gap: name it, explain why it matters, and "
                    "estimate its priority (High / Medium / Low)."
                ),
            },
            {
                "position": 3,
                "title": "Recommendations",
                "instructions": (
                    "For each gap identified above, propose one or more concrete improvement actions. "
                    "Each recommendation must include: the action, expected outcome, and "
                    "the gap it addresses. Avoid generic advice — ground recommendations "
                    "in the specific context shown by the documents."
                ),
            },
            {
                "position": 4,
                "title": "Implementation Roadmap",
                "instructions": (
                    "Convert the recommendations into a phased roadmap. "
                    "Organize actions into three horizons:\n"
                    "- **Short term (0–6 months)**: quick wins, low effort, high visibility.\n"
                    "- **Medium term (6–18 months)**: structural changes requiring planning.\n"
                    "- **Long term (18+ months)**: systemic or capital-intensive initiatives.\n"
                    "For each horizon, list the actions, suggested responsible parties, "
                    "and key success indicators."
                ),
            },
        ],
    },
    {
        "name": "Stakeholder Report Brief",
        "slug": "ecofilia-stakeholder-report-brief",
        "description": (
            "3-step copilot that adapts document findings into three audience-specific outputs: "
            "executive brief, technical summary, and external talking points."
        ),
        "allowed_contexts": ["project", "repository", "document"],
        "system_prompt": (
            "You are Ecofilia, a sustainability communications specialist. "
            "Adapt the same core content to three distinct audiences. "
            "Maintain accuracy while adjusting depth and tone for each."
        ),
        "temperature": 0.5,
        "steps": [
            {
                "position": 1,
                "title": "Executive Brief",
                "instructions": (
                    "Write a 1-page executive brief for senior leadership or a board audience. "
                    "Lead with strategic relevance: what matters, why it matters now, "
                    "and what decisions or actions are recommended. "
                    "Avoid technical jargon. Use no more than 4 bullet points plus a 1-paragraph summary. "
                    "Base all content on the provided documents."
                ),
            },
            {
                "position": 2,
                "title": "Technical Findings Summary",
                "instructions": (
                    "Write a detailed technical summary for specialists, project managers, or "
                    "sustainability teams. Include data, methodology references, limitations, "
                    "and evidence from the documents. Use structured sections with headers. "
                    "This section can be longer and more dense — the audience is technical."
                ),
            },
            {
                "position": 3,
                "title": "External Communication Talking Points",
                "instructions": (
                    "Draft 5–8 concise talking points suitable for external audiences "
                    "(investors, clients, press, or regulators). Each point should be "
                    "1–2 sentences, factual, positive in framing, and verifiable from the documents. "
                    "Avoid greenwashing — only include claims that are explicitly supported."
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
    dependencies = [("skill", "0002_seed_ecofilia_skills")]
    operations = [migrations.RunPython(seed_skills, unseed_skills)]
