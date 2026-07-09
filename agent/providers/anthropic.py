"""Anthropic API provider — Claude models with full tool-use and image support."""

from __future__ import annotations

import logging

import anthropic

from .base import (
    BaseProvider,
    ImageBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    ToolSpec,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseProvider):
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    def supports_images(self) -> bool:
        return True  # all Claude models support images

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Message:
        # Convert to Anthropic API format
        system = self.system_prompt()
        api_messages = [_to_api_msg(m) for m in messages]

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system,
            messages=api_messages,
            tools=tools,
            tool_choice={"type": "auto"},
        )

        return _from_api_response(response)


def _to_api_msg(msg: Message) -> dict:
    """Convert our Message to Anthropic API message dict."""
    content: list[dict] = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageBlock):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": block.mime_type,
                    "data": block.source.decode("ascii") if isinstance(block.source, bytes) else block.source,
                },
            })
        elif isinstance(block, ToolUseBlock):
            content.append({
                "type": "tool_use",
                "id": block.tool_id,
                "name": block.tool_name,
                "input": block.input,
            })
        elif isinstance(block, ToolResultBlock):
            content.append({
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": block.content,
                "is_error": block.is_error,
            })
    return {"role": msg.role, "content": content}


def _from_api_response(resp) -> Message:
    """Convert Anthropic API response to our Message."""
    blocks: list = []
    for block in resp.content:
        if block.type == "text":
            blocks.append(TextBlock(text=block.text))
        elif block.type == "tool_use":
            blocks.append(ToolUseBlock(
                tool_id=block.id,
                tool_name=block.name,
                input=block.input,
            ))

    return Message(
        role="assistant",
        content=blocks,
        model=resp.model,
        stop_reason=resp.stop_reason,
        usage={
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    )
