"""Agent configuration — loaded from .env files, overridable via environment variables.

Priority (low → high):
  1. ../.env       (project root — shared vars like WIKI_ROOT, OLLAMA_URL)
  2. .env          (agent/ directory — agent-specific overrides)
  3. OS environment (highest priority)
"""

import os
from pathlib import Path

# Project root (where the main .env lives)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """手动加载 .env 文件，优先级: OS 环境变量 > agent/.env > ../.env

    不使用 python-dotenv 的 load_dotenv()，因为它在 Windows 上对 override 的处理不一致。
    """

    env_values: dict[str, str] = {}

    # 按优先级从低到高读取（后面的覆盖前面的）
    env_files = [
        (_PROJECT_ROOT / ".env", "../.env"),                            # 1. 项目根（最低）
        (Path(__file__).resolve().parent / ".env", "agent/.env"),       # 2. agent 目录（覆盖项目根）
    ]

    for env_path, _label in env_files:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            env_values[key] = value

    # 写入 os.environ（setdefault 确保已有的 OS 环境变量不被覆盖）
    for key, value in env_values.items():
        os.environ.setdefault(key, value)


_load_dotenv()

# ── Provider ──────────────────────────────────────────────────

PROVIDER = os.getenv("AGENT_PROVIDER", "anthropic")
"""Provider type: 'anthropic' | 'openai_compat' | 'ollama'"""

MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")
"""Model name for the chosen provider."""

# API key — pick the right env var based on provider
if PROVIDER == "anthropic":
    API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
elif PROVIDER == "openai_compat":
    API_KEY = (
        os.getenv("MINIMAX_API_KEY", "")
        or os.getenv("DEEPSEEK_API_KEY", "")
        or os.getenv("KIMI_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
        or os.getenv("ANTHROPIC_API_KEY", "")  # last resort (e.g. routed through openrouter)
    )
elif PROVIDER == "ollama":
    API_KEY = ""  # Ollama is local, no key needed
else:
    API_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # fallback

API_BASE = os.getenv("AGENT_API_BASE", "")
"""OpenAI-compatible base URL. For DeepSeek: https://api.deepseek.com/v1"""

# ── Ollama ────────────────────────────────────────────────────

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# ── Wiki ──────────────────────────────────────────────────────

WIKI_ROOT = Path(os.getenv("WIKI_ROOT", "./wiki_data/"))
if not WIKI_ROOT.is_absolute():
    WIKI_ROOT = (_PROJECT_ROOT / WIKI_ROOT).resolve()

# ── Agent behavior ────────────────────────────────────────────

SCAN_INTERVAL = int(os.getenv("AGENT_SCAN_INTERVAL", "60"))
"""Seconds between scans of sources/."""

LOG_FILE = Path(os.getenv("AGENT_LOG_FILE", str(Path(__file__).parent / "agent.log")))

# ── Git ───────────────────────────────────────────────────────

GIT_USER_NAME = os.getenv("AGENT_GIT_NAME", "LLM Wiki Agent")
GIT_USER_EMAIL = os.getenv("AGENT_GIT_EMAIL", "agent@llmwiki.local")

# ── Version ────────────────────────────────────────────────────

VERSION = "0.4.0"
"""Agent 版本号，记录在日志和 git commit 中。"""

# ── Limits ────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "50"))
"""Maximum tool-calling rounds per ingest (prevents infinite loops).

50 rounds accommodates PDF ingest flows: extract → read (paginated) →
search → write wiki pages → write index/log/overview → commit. 30 was
too tight for full PDFs.
"""

# ── Python interpreter for PDF extraction ─────────────────────

PYTHON_BIN = os.getenv("AGENT_PYTHON_BIN", "")
"""Path to a Python interpreter that has pdf_oxide installed.

Used by the bash tool's PDF extraction recipes. If empty, the bash tool
auto-detects (Windows: miniconda3, anaconda3, python launcher; POSIX: python3).
Set this explicitly if your install lives in a non-standard location.
"""
# Auto-detect on Windows when not specified
if not PYTHON_BIN and os.name == "nt":
    _candidates = [
        r"C:\ProgramData\miniconda3\python.exe",
        r"C:\ProgramData\Anaconda3\python.exe",
        r"C:\Python310\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python312\python.exe",
    ]
    for c in _candidates:
        if Path(c).is_file():
            PYTHON_BIN = c
            break
    # Fall back to the Windows py launcher — git bash may not see this
    if not PYTHON_BIN:
        PYTHON_BIN = "py"
