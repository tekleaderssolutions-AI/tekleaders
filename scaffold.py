import os

dirs = [
    "TalentForgeAI/src/core/database",
    "TalentForgeAI/src/core/security",
    "TalentForgeAI/src/core/events",
    "TalentForgeAI/src/modules/agency/domain",
    "TalentForgeAI/src/modules/agency/application",
    "TalentForgeAI/src/modules/agency/infrastructure",
    "TalentForgeAI/src/modules/agency/presentation",
    "TalentForgeAI/src/modules/recruitment/domain",
    "TalentForgeAI/src/modules/recruitment/application",
    "TalentForgeAI/src/modules/recruitment/infrastructure",
    "TalentForgeAI/src/modules/recruitment/presentation",
    "TalentForgeAI/src/modules/scheduling/domain",
    "TalentForgeAI/src/modules/scheduling/application",
    "TalentForgeAI/src/modules/scheduling/infrastructure",
    "TalentForgeAI/src/modules/scheduling/presentation",
    "TalentForgeAI/src/modules/ai_processing/domain",
    "TalentForgeAI/src/modules/ai_processing/application",
    "TalentForgeAI/src/modules/ai_processing/infrastructure",
    "TalentForgeAI/src/modules/ai_processing/presentation",
    "TalentForgeAI/src/modules/communications/domain",
    "TalentForgeAI/src/modules/communications/application",
    "TalentForgeAI/src/modules/communications/infrastructure",
    "TalentForgeAI/src/modules/communications/presentation",
    "TalentForgeAI/tests/unit",
    "TalentForgeAI/tests/integration",
]

for d in dirs:
    os.makedirs(d, exist_ok=True)
    
print("Successfully created TalentForgeAI directory structure!")
