#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Core Chat Overlay — Token Estimation Utilities

Extracted from chat_overlay_monolith.py.
Contains token estimation, truncation, and response token calculation.
"""

from __future__ import annotations

from overlay.constants import (
    MAX_SAFE_TOKENS,
    CHARS_PER_TOKEN,
    LLM_CONTEXT_SIZE,
    MIN_RESPONSE_TOKENS,
)


def _estimate_tokens(text: str) -> int:
    """Estimate token count with content-aware heuristics.

    Different content types have different token densities:
    - German prose: ~1.3 chars/token
    - URLs/paths:   ~3.5 chars/token (subword pieces)
    - Code/JSON:    ~2.5 chars/token (operators, braces tokenize individually)
    - Whitespace-heavy: lower density
    """
    if not text:
        return 0
    import re
    tokens = 0
    remaining = text

    # Extract and count URLs separately (~3.5 chars/token)
    urls = re.findall(r'https?://\S+', remaining)
    for url in urls:
        tokens += max(1, int(len(url) / 3.5))
        remaining = remaining.replace(url, '', 1)

    # Count code-like segments (lines with braces, brackets, operators)
    code_chars = 0
    prose_chars = 0
    for line in remaining.split('\n'):
        stripped = line.strip()
        if stripped and (stripped.startswith('{') or stripped.startswith('[')
                        or stripped.endswith(';') or stripped.endswith('{')
                        or '=' in stripped and '==' not in stripped):
            code_chars += len(line)
        else:
            prose_chars += len(line)

    tokens += max(0, int(code_chars / 2.5))
    tokens += max(0, int(prose_chars / CHARS_PER_TOKEN))

    return tokens + 1


def _truncate_to_token_limit(text: str, max_tokens: int = MAX_SAFE_TOKENS) -> str:
    """Truncate text to fit within token limit."""
    estimated = _estimate_tokens(text)
    if estimated <= max_tokens:
        return text
    # Calculate how many chars to keep
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    truncated = text[:max_chars]
    # Find a good break point (newline or space)
    last_break = max(truncated.rfind('\n'), truncated.rfind(' '))
    if last_break > max_chars * 0.8:  # Only use break if it's not too far back
        truncated = truncated[:last_break]
    return truncated + "\n[...gekürzt...]"


def _calculate_response_tokens(input_text: str) -> int:
    """
    Calculate available tokens for response based on input size.

    LLM context = input_tokens + output_tokens (4096 total)
    We want responses to NEVER be truncated, so we dynamically allocate
    as many tokens as possible for the response.
    """
    input_tokens = _estimate_tokens(input_text)
    # Available = Total context - Input - Safety margin
    # Using 4096 as actual server context (verified: --ctx-size 4096)
    available = LLM_CONTEXT_SIZE - input_tokens - 50  # 50 token safety margin
    # Minimum 1000 tokens for response, cap at 2000 to prevent timeouts
    return max(1000, min(available, 2000))
