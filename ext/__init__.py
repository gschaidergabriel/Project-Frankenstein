# E-SIR v2.5 "Genesis Fortress"
# Recursive Self-Improvement Protocol

from .e_sir import (
    ESIR,
    get_esir,
    propose_file_modification,
    propose_tool_creation,
    safe_file_transaction,
    ProposedAction,
    ActionType as ESIRActionType,
    DecisionResult,
)

# E-SMC v1.0 "Sovereign"
# Evolutionary System-Management & Configuration
from .sovereign import (
    ESMC,
    get_sovereign,
    propose_installation,
    propose_sysctl,
    SystemAction,
    ActionType as ESMCActionType,
    ActionStatus,
    PROTECTED_PACKAGES,
)

# AKAM v1.0 - Autonomous Knowledge Acquisition Module
from .akam import (
    AKAM,
    get_akam,
    check_and_research,
    Claim,
    ResearchSession,
    AKAMStatus,
)

__all__ = [
    # E-SIR
    "ESIR",
    "get_esir",
    "propose_file_modification",
    "propose_tool_creation",
    "safe_file_transaction",
    "ProposedAction",
    "ESIRActionType",
    "DecisionResult",
    # E-SMC Sovereign
    "ESMC",
    "get_sovereign",
    "propose_installation",
    "propose_sysctl",
    "SystemAction",
    "ESMCActionType",
    "ActionStatus",
    "PROTECTED_PACKAGES",
    # AKAM
    "AKAM",
    "get_akam",
    "check_and_research",
    "Claim",
    "ResearchSession",
    "AKAMStatus",
]
