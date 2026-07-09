"""Tool registry — maps tool names to schemas and execution functions."""

from __future__ import annotations

from typing import Any, Callable

from . import bash, edit_file, extract_pdf, lint, manifest, read_file, view_image, write_file

# All registered tools
_ALL: list[dict[str, Any]] = []


def register(module, async_execute: Callable | None = None, sync_execute: Callable | None = None) -> None:
    """Register a tool module.

    module must define: DESCRIPTION (str), JSON_SCHEMA (dict)
    and either async_execute or sync_execute.
    """
    tool_spec = {
        "name": module.__name__.split(".")[-1],
        "description": module.DESCRIPTION,
        "input_schema": module.JSON_SCHEMA,
    }
    _ALL.append({
        "spec": tool_spec,
        "async_execute": getattr(module, "execute", None),
        "module": module,
    })


register(bash)
register(read_file)
register(write_file)
register(edit_file)
register(view_image)
register(manifest)
register(extract_pdf)
register(lint)


def all_tools() -> list[dict[str, Any]]:
    """Return all tools in Anthropic-compatible format."""
    return [t["spec"] for t in _ALL]


async def execute_tool(tool_name: str, tool_input: dict[str, Any], supports_images: bool = False) -> dict:
    """Execute a tool by name. Returns a result dict (to be serialized for the model)."""
    for t in _ALL:
        if t["spec"]["name"] == tool_name:
            fn = t["async_execute"]
            if fn is None:
                fn = t["module"].execute

            # view_image needs supports_images flag
            if tool_name == "view_image":
                tool_input = dict(tool_input)
                tool_input.setdefault("supports_images", supports_images)

            import inspect
            if inspect.iscoroutinefunction(fn):
                result = await fn(**tool_input)
            else:
                result = fn(**tool_input)
            return result

    return {"error": f"Unknown tool: {tool_name}"}
