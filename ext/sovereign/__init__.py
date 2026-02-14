"""
E-SMC/V "Sovereign Vision" v3.0 - Evolutionary System-Management & Visual Validation
======================================================================================

Frank's Fähigkeit zur sicheren System-Verwaltung mit visueller Validierung.

Die Eisernen Gesetze:
1. Kein direkter Root-Zugriff - nur über frank-execute Whitelist
2. Backup vor JEDER Änderung (Snapshot-Axiom)
3. Keine kritischen Pakete entfernen (Dependencies-Sentinel)
4. Gaming-Mode = 100% Lock für alle Systemänderungen
5. Auto-Rollback bei System-Instabilität

E-SMC/V v3.0 Erweiterungen:
6. Anti-Loop-Sentinel: Max 2x denselben Parameter in 24h
7. Kausal-Check: 2 Datenquellen erforderlich
8. VCB Integration: Visuelle Validierung vor Änderungen
9. HUD Logging: Transparente Anzeige aller Aktionen

Usage:
    from ext.sovereign import get_sovereign, propose_installation

    sovereign = get_sovereign()

    # Status prüfen
    status = sovereign.get_status()

    # Paket-Installation mit Kausal-Check
    result = sovereign.propose_installation(
        "htop",
        reason="CPU-Monitoring verbessern",
        sources=["log_error", "user_request"]  # 2 Quellen für Legitimität
    )

    # Visual Audit durchführen
    from ext.sovereign import get_vcb_bridge
    vcb = get_vcb_bridge()
    audit = vcb.visual_audit("Hohe CPU-Last erkannt")
"""

from .e_smc import (
    # Hauptcontroller
    ESMC,
    get_sovereign,

    # Convenience-Funktionen
    propose_installation,
    propose_sysctl,

    # Datenstrukturen
    SystemAction,
    ActionType,
    ActionStatus,

    # Komponenten (für erweiterte Nutzung)
    SovereignDatabase,
    RiskAnalyzer,
    DependenciesSentinel,
    SnapshotManager,
    GamingModeLock,
    VDPExecutor,

    # E-SMC/V v3.0 Komponenten
    AntiLoopSentinel,
    CausalValidator,

    # Konstanten
    PROTECTED_PACKAGES,
    ALLOWED_SYSCTL,
    MAX_DAILY_INSTALLATIONS,
    MAX_DAILY_CONFIG_CHANGES,
    CONFIDENCE_THRESHOLD,
)

# E-SMC/V v3.0: VCB Integration
from .vcb_integration import (
    VCBBridge,
    get_vcb_bridge,
    VisualAuditResult,
    CorrelationResult,
)

# E-SMC/V v3.0: HUD Logger
from .hud_logger import (
    SovereignHUDLogger,
    get_hud_logger,
)

__all__ = [
    # Main
    "ESMC",
    "get_sovereign",
    "propose_installation",
    "propose_sysctl",

    # Data
    "SystemAction",
    "ActionType",
    "ActionStatus",

    # Components
    "SovereignDatabase",
    "RiskAnalyzer",
    "DependenciesSentinel",
    "SnapshotManager",
    "GamingModeLock",
    "VDPExecutor",

    # E-SMC/V v3.0 Components
    "AntiLoopSentinel",
    "CausalValidator",

    # VCB Integration
    "VCBBridge",
    "get_vcb_bridge",
    "VisualAuditResult",
    "CorrelationResult",

    # HUD Logger
    "SovereignHUDLogger",
    "get_hud_logger",

    # Constants
    "PROTECTED_PACKAGES",
    "ALLOWED_SYSCTL",
    "MAX_DAILY_INSTALLATIONS",
    "MAX_DAILY_CONFIG_CHANGES",
    "CONFIDENCE_THRESHOLD",
]

__version__ = "3.0.0"
