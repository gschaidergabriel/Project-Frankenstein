"""
Intent Parser for Natural Language Commands
"""

import re
from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class Intent:
    """Parsed intent from user input"""
    action: str
    critical: bool
    data: Dict[str, Any]
    confirmation_message: str
    success_message: str
    original_text: str


class IntentParser:
    """Parses natural language to intents"""

    INTENTS = {
        # Critical actions (require confirmation)
        'save': {
            'patterns': [
                r'\bsave\b',
                r'\bspeicher(e|n|t)?\b',
                r'\bsicher(e|n|t)?\b',
            ],
            'critical': True,
            'confirmation': "Should I save the document?",
            'success': "Document saved"
        },
        'export': {
            'patterns': [
                r'\bexport\b',
                r'\bas (pdf|docx|tex|html|md)\b',
                r'\bconvert\b',
                r'\bexport(iere|ieren|iert)?\b',
                r'\bkonvertier(e|en|t)?\b',
            ],
            'critical': True,
            'confirmation': "Should I export the document?",
            'success': "Export complete"
        },
        'close': {
            'patterns': [
                r'\bclose\b',
                r'\bexit\b',
                r'\bquit\b',
                r'\bschlie(ß|ss)(e|en|t)?\b',
                r'\bbeend(e|en|et)?\b',
            ],
            'critical': True,
            'confirmation': "Close Writer?",
            'success': "Writer is closing"
        },

        # Non-critical actions
        'run': {
            'patterns': [
                r'\brun\b',
                r'\bexecute\b',
                r'\bstart\b',
                r'\btest\b',
                r'\bausfüh?r(e|en|t)?\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Running code"
        },
        'new': {
            'patterns': [
                r'\bnew (document|file)\b',
                r'\bnew\b',
                r'\bneu(es)? (dokument|datei)\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "New document created"
        },
        'rewrite': {
            'patterns': [
                r'\brewrite\b',
                r'\brephrase\b',
                r'\breformulate\b',
                r'\bumschreiben\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Text rewritten"
        },
        'expand': {
            'patterns': [
                r'\bexpand\b',
                r'\belaborate\b',
                r'\bmore details?\b',
                r'\berweiter(e|n|t)?\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Text expanded"
        },
        'shorten': {
            'patterns': [
                r'\bshorten\b',
                r'\bsummariz(e|ieren)\b',
                r'\bcompress\b',
                r'\bkürz(e|en|t)?\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Text shortened"
        },
        'explain': {
            'patterns': [
                r'\bexplain\b',
                r'\bwhat (does|is|means)\b',
                r'\berklär(e|en|t)?\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Explanation generated"
        },
        'translate': {
            'patterns': [
                r'\btranslate\b',
                r'\bto (english|german|french|spanish)\b',
                r'\büberseh?tz(e|en|t)?\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Translation complete"
        },
        'format': {
            'patterns': [
                r'\bformat\b',
                r'\bcode block\b',
                r'\binsert\b.*\bcode\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Formatting applied"
        },
        'help': {
            'patterns': [
                r'\bhelp\b',
                r'\bhilfe\b',
                r'\bwhat can you\b',
                r'\bhow (do|can) I\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': None
        }
    }

    def __init__(self):
        # Compile patterns
        self.compiled_patterns = {}
        for intent_name, intent_data in self.INTENTS.items():
            patterns = intent_data['patterns']
            combined = '|'.join(f'({p})' for p in patterns)
            self.compiled_patterns[intent_name] = re.compile(combined, re.IGNORECASE)

    def parse(self, text: str) -> Optional[Intent]:
        """Parse text to intent"""
        text_lower = text.lower()

        # Extract format if mentioned
        format_match = re.search(r'\b(pdf|docx|tex|html|md|markdown|word|latex)\b', text_lower)
        export_format = format_match.group(1) if format_match else None

        # Map format aliases
        format_map = {
            'word': 'docx',
            'latex': 'tex',
            'markdown': 'md'
        }
        if export_format in format_map:
            export_format = format_map[export_format]

        # Check each intent
        for intent_name, pattern in self.compiled_patterns.items():
            if pattern.search(text_lower):
                intent_data = self.INTENTS[intent_name]

                # Build data dict
                data = {}
                if intent_name == 'export' and export_format:
                    data['format'] = export_format

                # Build confirmation message - use empty string instead of None for non-critical
                confirmation = intent_data.get('confirmation') or ''
                if intent_name == 'export' and export_format:
                    confirmation = f"Should I export as {export_format.upper()}?"

                return Intent(
                    action=intent_name,
                    critical=intent_data['critical'],
                    data=data,
                    confirmation_message=confirmation,
                    success_message=intent_data.get('success', f'{intent_name} executed'),
                    original_text=text
                )

        return None

    def get_help_text(self) -> str:
        """Get help text for available commands"""
        return """
**Available Commands:**

**File:**
- "Save" - Save document
- "Export as PDF/DOCX/TEX" - Export document
- "Close" / "Exit" - Close Writer

**Code (Coding Mode):**
- "Run" / "Execute" / "Test" - Run code

**Edit Text:**
- "Rewrite" - Rephrase text
- "Expand" - Add more details
- "Shorten" - Compress text
- "Translate" - Translate between languages
- "Explain" - Explain code/text

**Other:**
- "Help" - Show this help
"""
