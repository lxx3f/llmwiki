"""Ollama provider — local LLM via Ollama API (httpx, no extra SDK needed)."""

from __future__ import annotations

import json
import logging

import httpx

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


class OllamaProvider(BaseProvider):
    def __init__(self, model: str, ollama_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = ollama_url.rstrip("/")
        self._supports_images = self._detect_vision(model)

    @staticmethod
    def _detect_vision(model: str) -> bool:
        vision_models = {"llava", "bakllava", "minicpm-v", "llama3.2-vision", "gemma3"}
        return any(v in model.lower() for v in vision_models)

    def supports_images(self) -> bool:
        return self._supports_images

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Message:
        system = self.system_prompt()
        api_messages = _to_ollama_msgs(system, messages)
        ollama_tools = _tools_to_ollama(tools) if tools else None

        payload = {
            "model": self.model,
            "messages": api_messages,
            "stream": False,
            "options": {"temperature": 0.3},
        }
        if ollama_tools:
            payload["tools"] = ollama_tools

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return _from_ollama_response(data)


def _to_ollama_msgs(system: str, messages: list[Message]) -> list[dict]:
    """Convert to Ollama chat messages."""
    result = [{"role": "system", "content": system}]
    for msg in messages:
        content = ""
        images: list[str] = []
        tool_calls: list[dict] | None = None

        for block in msg.content:
            if isinstance(block, TextBlock):
                content += block.text
            elif isinstance(block, ImageBlock):
                b64 = block.source.decode("ascii") if isinstance(block.source, bytes) else block.source
                images.append(b64)
            elif isinstance(block, ToolUseBlock):
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append({
                    "function": {
                        "name": block.tool_name,
                        "arguments": block.input,
                    }
                })
            elif isinstance(block, ToolResultBlock):
                content += f"\n[Tool result for {block.tool_use_id}]: {block.content}\n"

        entry: dict = {"role": msg.role, "content": content}
        if images:
            entry["images"] = images
        if tool_calls and msg.role == "assistant":
            entry["tool_calls"] = tool_calls
        result.append(entry)
    return result


def _tools_to_ollama(tools: list[ToolSpec]) -> list[dict]:
    """Ollama tool format is close to OpenAI's."""
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        })
    return result


def _from_ollama_response(data: dict) -> Message:
    """Parse Ollama chat response into our Message."""
    msg = data.get("message", {})
    blocks: list = []

    text = msg.get("content", "")
    if text:
        blocks.append(TextBlock(text=text))

    # Ollama returns tool calls in message.tool_calls
    tool_calls = msg.get("tool_calls", [])
    for tc in tool_calls:
        func = tc.get("function", {})
        args = func.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        blocks.append(ToolUseBlock(
            tool_id=tc.get("id", f"call_{len(blocks)}"),
            tool_name=func.get("name", "unknown"),
            input=args,
        ))

    return Message(
        role="assistant",
        content=blocks,
        model=data.get("model", ""),
        stop_reason=data.get("done_reason", "stop"),
        usage={
            "input_tokens": data.get("prompt_eval_count", 0),
            "output_tokens": data.get("eval_count", 0),
        },
    )
