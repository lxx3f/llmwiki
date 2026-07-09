"""Base provider interface and shared data structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Message blocks ────────────────────────────────────────────


@dataclass
class TextBlock:
    text: str


@dataclass
class ImageBlock:
    source: bytes
    mime_type: str
    source_path: str = ""  # relative path for reference


@dataclass
class ToolUseBlock:
    tool_id: str
    tool_name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock


# ── Message ───────────────────────────────────────────────────


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: list[ContentBlock]
    model: str = ""
    stop_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Join all text blocks into a single string (for log / display)."""
        parts: list[str] = []
        for block in self.content:
            if isinstance(block, TextBlock):
                parts.append(block.text)
        return "\n".join(parts)

    def has_tool_calls(self) -> bool:
        return any(isinstance(b, ToolUseBlock) for b in self.content)

    def tool_calls(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]


# ── Tool spec (Anthropic format, shared) ──────────────────────


ToolSpec = dict[str, Any]
"""Anthropic-format tool definition:

{
    "name": "bash",
    "description": "...",
    "input_schema": {
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}
"""


# ── Provider interface ────────────────────────────────────────


class BaseProvider(ABC):
    """Unified interface for different LLM API providers."""

    def system_prompt(self) -> str:
        """Return the system prompt for the ingest workflow.

        Substitutes {python_bin} with the resolved Python interpreter
        (config.PYTHON_BIN) so the agent uses an interpreter that has
        pdf_oxide installed. Uses str.replace (not .format) because the
        prompt body contains other {placeholders} that would clash.
        """
        from skills.ingest import SYSTEM_PROMPT
        try:
            import config
            return SYSTEM_PROMPT.replace("{python_bin}", config.PYTHON_BIN or "python")
        except Exception:
            return SYSTEM_PROMPT

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Message:
        """Send a conversation turn and return the model's response.

        The response Message may contain TextBlock(s) and/or ToolUseBlock(s).
        """
        ...

    def supports_images(self) -> bool:
        """Whether this provider/model can accept ImageBlock in messages."""
        return False
