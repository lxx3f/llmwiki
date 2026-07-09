"""OpenAI-compatible API provider — works with OpenAI, DeepSeek, Kimi, Qwen, etc."""

from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

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

# Map our tool format to OpenAI tool format
# (OpenAI uses a slightly different schema structure)


class OpenAICompatProvider(BaseProvider):
    def __init__(self, model: str, api_key: str, base_url: str = ""):
        self.model = model
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)
        self._supports_images = self._detect_vision(model)

    @staticmethod
    def _detect_vision(model: str) -> bool:
        vision_models = {
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-vision",
            "claude",  # may be routed through openai compat
            "gemini", "qvq", "qwen-vl", "qwen2.5-vl",
            "llava", "bakllava", "minicpm-v",
        }
        model_lower = model.lower()
        return any(v in model_lower for v in vision_models)

    def supports_images(self) -> bool:
        return self._supports_images

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Message:
        system = self.system_prompt()
        api_messages = [{"role": "system", "content": system}]
        api_messages.extend(_to_openai_msgs(messages))

        openai_tools = _tools_to_openai(tools) if tools else None

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            tools=openai_tools,
            tool_choice="auto" if openai_tools else None,
            max_tokens=8192,
        )

        return _from_openai_response(response)


def _to_openai_msgs(messages: list[Message]) -> list[dict]:
    """Convert our Messages to OpenAI API message format.

    OpenAI/MiniMax/DeepSeek tool calling protocol:
      - ToolUseBlock  → role: "assistant" with tool_calls array
      - ToolResultBlock → role: "tool" with tool_call_id (NOT role: "user")
    """
    result = []
    for msg in messages:
        # Count tool result blocks — if ALL content blocks are ToolResultBlock,
        # emit them as individual role:"tool" messages
        tool_results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
        non_tool = [b for b in msg.content if not isinstance(b, ToolResultBlock)]

        if tool_results and not non_tool:
            # Pure tool-result message → emit each as role:"tool"
            for tr in tool_results:
                result.append({
                    "role": "tool",
                    "tool_call_id": tr.tool_use_id,
                    "content": tr.content,
                })
            continue

        # Mixed or non-tool message
        content = []
        tool_calls = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                content.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageBlock):
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{block.mime_type};base64,{block.source.decode('ascii') if isinstance(block.source, bytes) else block.source}",
                    },
                })
            elif isinstance(block, ToolUseBlock):
                tool_calls.append({
                    "id": block.tool_id,
                    "type": "function",
                    "function": {
                        "name": block.tool_name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    },
                })
            elif isinstance(block, ToolResultBlock):
                # Tool result inside a mixed message — embed as text (fallback)
                content.append({
                    "type": "text",
                    "text": json.dumps({"tool_result": block.content}, ensure_ascii=False),
                })

        item: dict = {"role": msg.role, "content": content if content else None}
        if tool_calls:
            item["tool_calls"] = tool_calls
            item["content"] = None  # OpenAI: tool_calls replace content
        result.append(item)
    return result


def _tools_to_openai(tools: list[ToolSpec]) -> list[dict]:
    """Convert Anthropic-format tools to OpenAI format."""
    openai_tools = []
    for t in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        })
    return openai_tools


def _from_openai_response(resp) -> Message:
    """Convert OpenAI API response to our Message."""
    choice = resp.choices[0]
    msg = choice.message
    blocks: list = []

    if msg.content:
        blocks.append(TextBlock(text=msg.content))

    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {"raw": tc.function.arguments}
            blocks.append(ToolUseBlock(
                tool_id=tc.id,
                tool_name=tc.function.name,
                input=args,
            ))

    return Message(
        role="assistant",
        content=blocks,
        model=resp.model,
        stop_reason=choice.finish_reason or "stop",
        usage={
            "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
        },
    )
