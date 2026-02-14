"""
Frank Writer - AI-Native Document & Code Editor

A collaborative text and code editor with Frank AI integration.
Supports Writer Mode (documents) and Coding Mode (with live preview).
"""

__version__ = "1.0.0"
__author__ = "Frank AI System"

from writer.editor import Document, WriterSourceView
from writer.ai import FrankBridge
from writer.config import WriterConfig

__all__ = ['Document', 'WriterSourceView', 'FrankBridge', 'WriterConfig']
