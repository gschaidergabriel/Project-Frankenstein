"""
Frank Writer Configuration
"""

import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class EditorConfig:
    """Editor settings"""
    font_family: str = "JetBrains Mono"
    font_size: int = 12
    tab_width: int = 4
    use_spaces: bool = True
    show_line_numbers: bool = True
    show_minimap: bool = True
    highlight_current_line: bool = True
    word_wrap: bool = True
    auto_indent: bool = True
    bracket_matching: bool = True


@dataclass
class ThemeConfig:
    """Theme settings"""
    writer_theme: str = "writer_light"
    coding_theme: str = "coding_monokai"
    ui_color_scheme: str = "default"  # default, prefer-dark, prefer-light


@dataclass
class AIConfig:
    """AI integration settings"""
    core_api_url: str = "http://127.0.0.1:8088"
    router_url: str = "http://127.0.0.1:8091"
    toolbox_url: str = "http://127.0.0.1:8096"
    suggestion_delay_ms: int = 500
    auto_suggest: bool = True
    confirm_critical_actions: bool = True


@dataclass
class SandboxConfig:
    """Sandbox settings"""
    timeout_sec: int = 30
    memory_mb: int = 512
    max_processes: int = 50
    allow_network: bool = False
    auto_fix_enabled: bool = True
    max_fix_attempts: int = 5


@dataclass
class ExportConfig:
    """Export settings"""
    default_pdf_style: str = "modern"
    pdf_page_size: str = "A4"
    pdf_font_family: str = "Libertinus Serif"
    pdf_font_size: int = 11
    include_toc: bool = True
    include_page_numbers: bool = True


@dataclass
class SaveConfig:
    """Auto-save and recovery settings"""
    autosave_enabled: bool = True
    autosave_interval_sec: int = 60
    spell_check_enabled: bool = True
    spell_language: str = "de_DE"


# Base directory for writer package (portable — no hardcoded paths)
_WRITER_PKG_DIR = Path(__file__).resolve().parent.parent

try:
    from config.paths import AICORE_CONFIG as _WRITER_CONFIG_BASE
except ImportError:
    _WRITER_CONFIG_BASE = Path.home() / ".config" / "frank"


@dataclass
class WriterConfig:
    """Main configuration class"""
    editor: EditorConfig = field(default_factory=EditorConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    save_config: SaveConfig = field(default_factory=SaveConfig)

    # Paths — B8 FIX: use relative paths derived from package location
    config_dir: Path = field(default_factory=lambda: _WRITER_CONFIG_BASE / "writer")
    data_dir: Path = field(default_factory=lambda: _WRITER_PKG_DIR / "data")
    schemas_dir: Path = field(default_factory=lambda: _WRITER_PKG_DIR / "schemas")

    def __post_init__(self):
        """Load config from file if exists"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"
        self.load()

    def load(self):
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)

                    # Validate that root is a dict
                    if not isinstance(data, dict):
                        print(f"Config error: Expected dict, got {type(data).__name__}")
                        return

                    # Validate and load each config section with type checking
                    if 'editor' in data and isinstance(data['editor'], dict):
                        self.editor = self._safe_load_config(EditorConfig, data['editor'], self.editor)
                    if 'theme' in data and isinstance(data['theme'], dict):
                        self.theme = self._safe_load_config(ThemeConfig, data['theme'], self.theme)
                    if 'ai' in data and isinstance(data['ai'], dict):
                        self.ai = self._safe_load_config(AIConfig, data['ai'], self.ai)
                    if 'sandbox' in data and isinstance(data['sandbox'], dict):
                        self.sandbox = self._safe_load_config(SandboxConfig, data['sandbox'], self.sandbox)
                    if 'export' in data and isinstance(data['export'], dict):
                        self.export = self._safe_load_config(ExportConfig, data['export'], self.export)
                    if 'save' in data and isinstance(data['save'], dict):
                        self.save_config = self._safe_load_config(SaveConfig, data['save'], self.save_config)
            except json.JSONDecodeError as e:
                print(f"Config error: Invalid JSON in config file: {e}")
            except PermissionError as e:
                print(f"Config error: Permission denied reading config: {e}")
            except Exception as e:
                print(f"Error loading config: {e}")

    def _safe_load_config(self, config_class, data: dict, default):
        """Safely load a config dataclass, validating types and using defaults for invalid values"""
        import dataclasses

        # Get the expected fields and their types from the dataclass
        field_types = {f.name: f.type for f in dataclasses.fields(config_class)}
        default_values = {f.name: getattr(default, f.name) for f in dataclasses.fields(config_class)}

        validated_data = {}
        for field_name, expected_type in field_types.items():
            if field_name in data:
                value = data[field_name]
                # Validate type matches expected type
                if self._validate_type(value, expected_type):
                    validated_data[field_name] = value
                else:
                    # Use default for invalid type
                    validated_data[field_name] = default_values[field_name]
                    print(f"Config warning: Invalid type for {field_name}, using default")
            else:
                # Field missing from config, use default
                validated_data[field_name] = default_values[field_name]

        try:
            return config_class(**validated_data)
        except Exception:
            # If construction still fails, return the original default
            return default

    def _validate_type(self, value, expected_type) -> bool:
        """Validate that a value matches the expected type"""
        # Handle basic types
        if expected_type == str:
            return isinstance(value, str)
        elif expected_type == int:
            return isinstance(value, int) and not isinstance(value, bool)
        elif expected_type == bool:
            return isinstance(value, bool)
        elif expected_type == float:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            # For complex types, just check it's not None
            return value is not None

    def save(self):
        """Save configuration to file"""
        try:
            data = {
                'editor': asdict(self.editor),
                'theme': asdict(self.theme),
                'ai': asdict(self.ai),
                'sandbox': asdict(self.sandbox),
                'export': asdict(self.export),
                'save': asdict(self.save_config),
            }
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_schema_path(self, category: str, name: str) -> Optional[Path]:
        """Get path to a schema file"""
        path = self.schemas_dir / category / f"{name}.yaml"
        return path if path.exists() else None

    def get_theme_css(self, mode: str) -> Path:
        """Get CSS file for current theme"""
        themes_dir = _WRITER_PKG_DIR / "themes"
        if mode == 'coding':
            return themes_dir / f"{self.theme.coding_theme}.css"
        return themes_dir / f"{self.theme.writer_theme}.css"
