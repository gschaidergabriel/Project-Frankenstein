"""Sidebar module"""
from .sidebar_manager import SidebarManager
from .chat_panel import ChatPanel
from .templates_panel import TemplatesPanel
from .outline_panel import OutlinePanel
from .files_panel import FilesPanel
from .intent_parser import IntentParser, Intent

__all__ = [
    'SidebarManager', 'ChatPanel', 'TemplatesPanel',
    'OutlinePanel', 'FilesPanel', 'IntentParser', 'Intent'
]
