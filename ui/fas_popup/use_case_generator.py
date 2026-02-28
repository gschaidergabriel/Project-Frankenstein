#!/usr/bin/env python3
"""
F.A.S. Use Case Generator
Generates personalized use-case explanations for discovered features.
"""

import re
from typing import Dict, List, Optional
from datetime import datetime


class UseCaseGenerator:
    """
    Generates use-case explanations for features.
    Explains not just WHAT a feature does, but WHY it's useful.
    """

    # Keywords that indicate feature types
    FEATURE_KEYWORDS = {
        "api": ["api", "client", "wrapper", "integration", "service", "endpoint"],
        "tool": ["tool", "utility", "helper", "handler", "processor"],
        "automation": ["automation", "scheduler", "cron", "task", "job", "worker"],
        "data": ["parser", "converter", "transformer", "extractor", "scraper"],
        "security": ["auth", "security", "encrypt", "token", "credential"],
        "cache": ["cache", "redis", "memcache", "store"],
        "database": ["database", "db", "sql", "query", "orm"],
        "network": ["http", "socket", "request", "fetch", "download"],
        "file": ["file", "path", "directory", "io", "read", "write"],
    }

    # Example prompts for each category
    EXAMPLE_PROMPTS = {
        "api": [
            "Fetch the latest data from {service}",
            "Update the status in {service}",
            "Sync with {service}",
        ],
        "tool": [
            "Run {action} automatically",
            "Process {input} with {tool}",
            "Help me with {task}",
        ],
        "automation": [
            "Schedule this task for later",
            "Run this on a regular basis",
            "Automate this workflow",
        ],
        "data": [
            "Extract data from {source}",
            "Convert {input} to {output}",
            "Parse this {format} file",
        ],
        "security": [
            "Secure these credentials",
            "Authenticate with {service}",
            "Encrypt this data",
        ],
        "cache": [
            "Cache this query",
            "Optimize the performance",
            "Store the result for reuse",
        ],
        "database": [
            "Query the database",
            "Store this data",
            "Search for {criteria}",
        ],
        "network": [
            "Download {resource}",
            "Send a request to {url}",
            "Check the connection to {host}",
        ],
        "file": [
            "Process these files",
            "Organize {directory}",
            "Find all {pattern} files",
        ],
    }

    def __init__(self):
        pass

    def generate_use_case(self, feature: Dict) -> Dict[str, str]:
        """
        Generate use-case explanation for a feature.

        Returns dict with:
        - title: Short title for the use-case box
        - why: Why this feature is useful
        - before_after: Before/After comparison
        - example: Example usage prompt
        - personal_relevance: Personal relevance note (if applicable)
        """
        # Store feature reference so _generate_why() can access genesis-specific fields
        self._current_feature = feature
        feature_type = feature.get("feature_type", "tool")
        name = feature.get("name", "Unknown")
        description = feature.get("description", "")
        code = feature.get("code_snippet", "")
        repo = feature.get("repo_name", "")

        # Detect category from name and code
        category = self._detect_category(name, description, code)

        # Generate components
        why = self._generate_why(feature_type, category, name, description)
        before_after = self._generate_before_after(category, name)
        example = self._generate_example(category, name, repo)
        personal = self._generate_personal_relevance(feature)

        return {
            "title": "WHY THIS FEATURE?",
            "why": why,
            "before_after": before_after,
            "example": example,
            "personal_relevance": personal,
        }

    def _detect_category(self, name: str, description: str, code: str) -> str:
        """Detect the category of a feature."""
        text = f"{name} {description} {code}".lower()

        scores = {}
        for category, keywords in self.FEATURE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[category] = score

        if scores:
            return max(scores, key=scores.get)
        return "tool"  # Default

    def _generate_why(self, feature_type: str, category: str, name: str, description: str) -> str:
        """Generate the 'why' explanation.

        For Genesis proposals (source="genesis"), uses proposal-specific data
        instead of generic templates.
        """
        # Check if this is a Genesis proposal with specific data
        if hasattr(self, '_current_feature') and self._current_feature:
            why_specific = self._current_feature.get("why_specific", "")
            if why_specific:
                return why_specific

        type_explanations = {
            "tool": "This tool extends Frank's capabilities directly and enables new tasks.",
            "api_wrapper": "This API integration connects Frank with external services for real-time data.",
            "utility": "This utility optimizes common operations and saves time.",
            "pattern": "This proven pattern improves code structure and maintainability.",
            # Genesis idea types
            "optimization": "Performance-Optimierung basierend auf Laufzeit-Analyse.",
            "fix": "Bugfix basierend auf Error-Log-Analyse.",
            "feature": "Neues Feature zur Erweiterung von Franks Fähigkeiten.",
            "exploration": "Explorative Idee zur Erweiterung des Horizonts.",
            "skill": "Skill-Entwicklung zur Verbesserung von Franks Fähigkeiten.",
            "personality_adjustment": "Emergente Persönlichkeits-Evolution.",
            "prompt_evolution": "Prompt-Template-Optimierung.",
        }

        category_benefits = {
            "api": "Direct access to external services without manual configuration.",
            "tool": "Automation of recurring tasks with a single command.",
            "automation": "Time-based or event-driven execution of tasks.",
            "data": "Efficient processing and transformation of data.",
            "security": "Secure handling of sensitive information.",
            "cache": "Faster response times through intelligent caching.",
            "database": "Structured data storage and retrieval.",
            "network": "Reliable network communication with error handling.",
            "file": "Flexible file management and processing.",
        }

        base = type_explanations.get(feature_type, type_explanations.get("tool", ""))
        benefit = category_benefits.get(category, "")

        return f"{base}\n\n{benefit}" if benefit else base

    def _generate_before_after(self, category: str, name: str) -> str:
        """Generate before/after comparison."""
        comparisons = {
            "api": {
                "before": "Manual API calls, error handling, rate limiting",
                "after": "Automatic handling, robust error recovery",
            },
            "tool": {
                "before": "Manual execution of multiple steps",
                "after": "One command handles everything automatically",
            },
            "automation": {
                "before": "Manual task triggering, easy to forget",
                "after": "Automatic, reliable execution",
            },
            "data": {
                "before": "Manual data processing, error-prone",
                "after": "Automatic, consistent transformation",
            },
            "security": {
                "before": "Insecure storage, manual handling",
                "after": "Secure, standards-compliant management",
            },
            "cache": {
                "before": "Slow repeated queries",
                "after": "Fast responses from cache",
            },
            "database": {
                "before": "Raw SQL, manual connection management",
                "after": "Abstracted, secure database access",
            },
            "network": {
                "before": "Simple requests without retry logic",
                "after": "Robust requests with automatic retry",
            },
            "file": {
                "before": "Manual file management, path issues",
                "after": "Consistent, cross-platform operations",
            },
        }

        comp = comparisons.get(category, comparisons["tool"])
        return f"BEFORE: {comp['before']}\nAFTER: {comp['after']}"

    def _generate_example(self, category: str, name: str, repo: str) -> str:
        """Generate example usage prompt."""
        examples = self.EXAMPLE_PROMPTS.get(category, self.EXAMPLE_PROMPTS["tool"])

        # Use first example, fill in placeholders
        example = examples[0]

        # Try to extract service/tool name
        service_name = self._extract_service_name(name, repo)

        example = example.replace("{service}", service_name)
        example = example.replace("{tool}", name)
        example = example.replace("{action}", "this task")
        example = example.replace("{input}", "this data")
        example = example.replace("{output}", "JSON")
        example = example.replace("{task}", "this task")
        example = example.replace("{source}", "this source")
        example = example.replace("{format}", "this")
        example = example.replace("{criteria}", "this criteria")
        example = example.replace("{resource}", "this resource")
        example = example.replace("{url}", "this URL")
        example = example.replace("{host}", "this host")
        example = example.replace("{directory}", "this directory")
        example = example.replace("{pattern}", "*.py")

        return f'Example: "Frank, {example}"'

    def _extract_service_name(self, name: str, repo: str) -> str:
        """Extract likely service name from feature name or repo."""
        # Common service patterns
        services = ["github", "gitlab", "slack", "discord", "twitter",
                    "google", "aws", "azure", "docker", "kubernetes"]

        text = f"{name} {repo}".lower()
        for service in services:
            if service in text:
                return service.capitalize()

        # Use feature name as fallback
        return name.split("_")[0].capitalize() if "_" in name else name

    def _generate_personal_relevance(self, feature: Dict) -> Optional[str]:
        """Generate personal relevance note based on user patterns."""
        confidence = feature.get("confidence_score", 0)

        if confidence >= 0.9:
            return "High match with your existing requirements"
        elif confidence >= 0.85:
            return "Fits well with your usage profile"

        return None

    def generate_short_description(self, feature: Dict) -> str:
        """Generate a short one-line description."""
        feature_type = feature.get("feature_type", "tool")
        name = feature.get("name", "Unknown")
        category = self._detect_category(
            name,
            feature.get("description", ""),
            feature.get("code_snippet", "")
        )

        descriptions = {
            "api": "API integration for external services",
            "tool": "Automated tool for Frank",
            "automation": "Workflow automation",
            "data": "Data processing and transformation",
            "security": "Security feature",
            "cache": "Performance optimization through caching",
            "database": "Database access and management",
            "network": "Network functionality",
            "file": "File management and processing",
        }

        return descriptions.get(category, "New functionality for Frank")


# Singleton
_generator: Optional[UseCaseGenerator] = None


def get_use_case_generator() -> UseCaseGenerator:
    """Get or create use case generator singleton."""
    global _generator
    if _generator is None:
        _generator = UseCaseGenerator()
    return _generator
