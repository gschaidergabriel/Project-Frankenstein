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
                r'\bspeicher(e|n|t)?\b',
                r'\bsave\b',
                r'\bsicher(e|n|t)?\b',
            ],
            'critical': True,
            'confirmation': "Soll ich das Dokument speichern?",
            'success': "Dokument gespeichert"
        },
        'export': {
            'patterns': [
                r'\bexport(iere|ieren|iert)?\b',
                r'\bals (pdf|docx|tex|html|md)\b',
                r'\bkonvertier(e|en|t)?\b',
                r'\berstell(e|en|t)? (ein )?(pdf|word|latex)\b',
            ],
            'critical': True,
            'confirmation': "Soll ich das Dokument exportieren?",
            'success': "Export abgeschlossen"
        },
        'close': {
            'patterns': [
                r'\bschlie(ß|ss)(e|en|t)?\b',
                r'\bbeend(e|en|et)?\b',
                r'\bclose\b',
                r'\bexit\b',
                r'\bzurück zum (chat|overlay)\b',
            ],
            'critical': True,
            'confirmation': "Writer schließen?",
            'success': "Writer wird geschlossen"
        },

        # Non-critical actions
        'run': {
            'patterns': [
                r'\bausfüh?r(e|en|t)?\b',
                r'\brun\b',
                r'\bstart(e|en|et)?\b',
                r'\btest(e|en|et)?\b',
                r'\bexecut(e|ieren)?\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Code wird ausgeführt"
        },
        'new': {
            'patterns': [
                r'\bneu(es)? (dokument|document|datei|file)\b',
                r'\bnew\b',
                r'\berstell(e|en|t)? neu\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Neues Dokument erstellt"
        },
        'rewrite': {
            'patterns': [
                r'\bschreib(e|en|t)? (das )?(um|neu)\b',
                r'\bformulier(e|en|t)? (das )?(um|neu)\b',
                r'\brewrite\b',
                r'\bumschreiben\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Text umgeschrieben"
        },
        'expand': {
            'patterns': [
                r'\berweiter(e|n|t)?\b',
                r'\bmehr details\b',
                r'\bausführlicher\b',
                r'\bexpand\b',
                r'\belaborate\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Text erweitert"
        },
        'shorten': {
            'patterns': [
                r'\bkürz(e|en|t)?\b',
                r'\bkomprimier(e|en|t)?\b',
                r'\bkürzer\b',
                r'\bshorten\b',
                r'\bsummariz(e|ieren)\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Text gekürzt"
        },
        'explain': {
            'patterns': [
                r'\berklär(e|en|t)?\b',
                r'\bexplain\b',
                r'\bwas (bedeutet|macht|ist)\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Erklärung generiert"
        },
        'translate': {
            'patterns': [
                r'\büberseh?tz(e|en|t)?\b',
                r'\btranslate\b',
                r'\bauf (englisch|deutsch|english|german)\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Übersetzung fertig"
        },
        'format': {
            'patterns': [
                r'\bformat(ier|iere|ieren|iert)?\b',
                r'\beinfügen\b.*\bcode\b',
                r'\bcode block\b',
            ],
            'critical': False,
            'confirmation': None,
            'success': "Formatierung angewendet"
        },
        'help': {
            'patterns': [
                r'\bhilfe\b',
                r'\bhelp\b',
                r'\bwas kannst du\b',
                r'\bwie (mache|kann) ich\b',
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
                    confirmation = f"Soll ich als {export_format.upper()} exportieren?"

                return Intent(
                    action=intent_name,
                    critical=intent_data['critical'],
                    data=data,
                    confirmation_message=confirmation,
                    success_message=intent_data.get('success', f'{intent_name} ausgeführt'),
                    original_text=text
                )

        return None

    def get_help_text(self) -> str:
        """Get help text for available commands"""
        return """
**Verfügbare Befehle:**

**Datei:**
- "Speichere" / "Save" - Dokument speichern
- "Exportiere als PDF/DOCX/TEX" - Exportieren
- "Schließen" / "Beenden" - Writer schließen

**Code (Coding Mode):**
- "Ausführen" / "Run" / "Teste" - Code ausführen

**Text bearbeiten:**
- "Schreib das um" - Text neu formulieren
- "Erweitern" - Text ausführlicher machen
- "Kürzen" - Text komprimieren
- "Übersetzen" - Zwischen DE/EN übersetzen
- "Erkläre" - Code/Text erklären

**Sonstiges:**
- "Hilfe" - Diese Hilfe anzeigen
"""
