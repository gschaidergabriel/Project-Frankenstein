"""Auto-fix module"""
from .engine import AutoFixEngine, AutoFixResult, FixAttempt
from .error_analyzer import ErrorAnalyzer, ErrorInfo, ErrorCategory
from .fix_strategies import (
    FixStrategy,
    FixResult,
    PythonFixStrategy,
    JavaScriptFixStrategy,
    BashFixStrategy,
    FixStrategyRegistry,
    get_fix_strategy_registry,
)
from .history import (
    FixHistory,
    FixSession,
    FixAttempt as HistoryFixAttempt,
    FixOutcome,
    ErrorStatistics,
    SessionStatistics,
)

__all__ = [
    # Engine
    'AutoFixEngine',
    'AutoFixResult',
    'FixAttempt',
    # Error Analyzer
    'ErrorAnalyzer',
    'ErrorInfo',
    'ErrorCategory',
    # Fix Strategies
    'FixStrategy',
    'FixResult',
    'PythonFixStrategy',
    'JavaScriptFixStrategy',
    'BashFixStrategy',
    'FixStrategyRegistry',
    'get_fix_strategy_registry',
    # History
    'FixHistory',
    'FixSession',
    'HistoryFixAttempt',
    'FixOutcome',
    'ErrorStatistics',
    'SessionStatistics',
]
