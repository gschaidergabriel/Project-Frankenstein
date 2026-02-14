"""
UI Tester - Autonomous UI Testing System for Frank Overlay.

A GTK4-based testing tool that uses Claude API for intelligent
autonomous testing and collaborative design improvement.

Usage:
    python3 -m ui.ui_tester.start_popup

Components:
    - start_popup: Initial duration selection
    - test_executor: Autonomous test orchestration
    - results_popup: Results display and design chat (SIDE PANEL - Overlay visible!)
    - design_proposer: CSS patch generator with live-reload
    - claude_client: Anthropic API integration
    - overlay_controller: Frank overlay automation
"""

__version__ = "3.1.0"

# Lazy imports to avoid circular dependencies
def start():
    """Launch the UI Tester start popup."""
    from .start_popup import main
    main()


def run_test(duration_minutes: int = 5):
    """Run a test programmatically."""
    from .test_executor import TestExecutor
    executor = TestExecutor(duration_minutes=duration_minutes)
    return executor.run()


def show_results(test_results=None):
    """Show the results popup."""
    from .results_popup import ResultsApp
    app = ResultsApp()
    app.run(None)


__all__ = [
    "start",
    "run_test",
    "show_results",
]
