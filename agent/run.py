"""LLM Wiki Agent — 常驻后台进程，自动扫描 sources/ 并执行 ingest。

用法:
    python run.py

环境变量:
    WIKI_ROOT   Wiki 根目录（默认为 ../wiki_data/）
    AGENT_PROVIDER  Provider: anthropic | openai_compat | ollama
    AGENT_MODEL     模型名（默认 claude-sonnet-5）
    具体见 config.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from providers import get_provider
from providers.base import (
    ImageBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from tools import all_tools, execute_tool

# ── stdout/stderr UTF-8 (avoid mojibake in NSSM-redirected logs) ─────
# Under NSSM, sys.stdout / sys.stderr are redirected to a UTF-8 log file
# but keep the parent's console code page. Forcing UTF-8 here makes
# Chinese (and other non-ASCII) characters survive intact into
# logs/agent.out.log, so /agent monitor + tail-logs.bat render cleanly.
for _stream_name in ('stdout', 'stderr'):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8')
        except Exception:
            pass  # best-effort; file handlers below already do UTF-8

# ── Logging ────────────────────────────────────────────────────

from logging.handlers import TimedRotatingFileHandler

# Resolve log level from config (e.g. "DEBUG" → logging.DEBUG)
_log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)

logger = logging.getLogger("agent")
logger.setLevel(logging.DEBUG)  # let handlers filter; logger captures everything

# Console handler (color-less, terse)
ch = logging.StreamHandler()
ch.setLevel(_log_level)
ch.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
))
logger.addHandler(ch)

# Ensure parent dirs exist
config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
config.LOG_ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)

# Main log: all levels, daily rotation, keep 7 backups (last week).
# Suffix defaults to %Y-%m-%d (set by `when='midnight'` rollover).
main_handler = TimedRotatingFileHandler(
    str(config.LOG_FILE),
    when="midnight",
    interval=1,
    backupCount=config.LOG_BACKUPS,
    encoding="utf-8",
    utc=False,  # local time, matches console output
)
main_handler.setLevel(logging.DEBUG)
# Filter out WARNING+ from main log so each level goes to exactly one file.
# This way the errors file is a focused signal, not a duplicate of the main log.
main_handler.addFilter(lambda r: r.levelno < logging.WARNING)
main_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger.addHandler(main_handler)

# Errors-only log: WARNING+ERROR, weekly rotation (Monday), keep 4 backups.
# Sole destination for warnings and errors — long-tail error history.
err_handler = TimedRotatingFileHandler(
    str(config.LOG_ERROR_FILE),
    when="W0",  # Monday
    interval=1,
    backupCount=config.LOG_ERROR_BACKUPS,
    encoding="utf-8",
    utc=False,
)
err_handler.setLevel(logging.WARNING)
err_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger.addHandler(err_handler)


def log(msg: str, *args: Any) -> None:
    """Log to both console and agent.log."""
    logger.info(msg, *args)


# ── State file (for /agent monitoring page) ──────────────────

STATE_FILE = Path(__file__).resolve().parent / ".state.json"

# ── Scan trigger file (sentinel for immediate scans) ─────────
# The API writes this file when a user clicks "立即扫描" in the dashboard.
# The main loop's sub-poll picks it up within ~1s regardless of SCAN_INTERVAL.
# Path MUST match the API side's SCAN_TRIGGER_FILE in api/main.py.
SCAN_TRIGGER_FILE = Path(__file__).resolve().parent / ".scan_requested"
SUB_POLL_INTERVAL = 1  # seconds between checks during sleep


async def _wait_with_trigger(seconds: int) -> bool:
    """Sleep up to `seconds`, but break early if SCAN_TRIGGER_FILE exists.

    Polls every SUB_POLL_INTERVAL seconds for snappy response without
    burning CPU. Returns True if the trigger file was found and consumed.
    """
    for _ in range(seconds):
        if SCAN_TRIGGER_FILE.exists():
            try:
                SCAN_TRIGGER_FILE.unlink()
            except FileNotFoundError:
                pass
            return True
        await asyncio.sleep(SUB_POLL_INTERVAL)
    return False


def _consume_trigger() -> bool:
    """Atomically check + remove the trigger file. Returns True if consumed.

    Used at the top of the main loop to handle the case where the trigger
    was set while the agent was busy with a previous scan.
    """
    if SCAN_TRIGGER_FILE.exists():
        try:
            SCAN_TRIGGER_FILE.unlink()
        except FileNotFoundError:
            pass
        return True
    return False


def _write_state(state: str, current_doc: str = "", branch: str = "",
                 round: int = 0, extra: dict | None = None) -> None:
    """Atomically write the agent state file. Best-effort — failures are silent."""
    payload = {
        "state": state,
        "current_doc": current_doc,
        "branch": branch,
        "round": round,
        "last_update": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    try:
        STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.debug("state file write failed: %s", e)


# ── Git helpers ────────────────────────────────────────────────


def _git(*args: str) -> subprocess.CompletedProcess | None:
    """Run a git command in WIKI_ROOT."""
    try:
        return subprocess.run(
            ["git"] + list(args),
            cwd=str(config.WIKI_ROOT),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except FileNotFoundError:
        logger.warning("git 未安装或不在 PATH 中")
        return None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("git %s 失败: %s", " ".join(args), e)
        return None


def setup_git() -> None:
    """Ensure WIKI_ROOT exists, is a git repo, and has user config set."""
    # 1. Create WIKI_ROOT if it doesn't exist
    if not config.WIKI_ROOT.exists():
        config.WIKI_ROOT.mkdir(parents=True, exist_ok=True)
        logger.info("已创建 wiki 目录: %s", config.WIKI_ROOT)

    # 2. Initialize git repo if needed
    git_dir = config.WIKI_ROOT / ".git"
    if not git_dir.exists():
        r = subprocess.run(
            ["git", "init"],
            cwd=str(config.WIKI_ROOT),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if r.returncode == 0:
            logger.info("已在 %s 初始化 git 仓库", config.WIKI_ROOT)
        else:
            logger.warning("git init 失败: %s", r.stderr.strip())

    # 3. Set user config
    _git("config", "user.name", config.GIT_USER_NAME)
    _git("config", "user.email", config.GIT_USER_EMAIL)


def bootstrap_default_kb() -> str | None:
    """Create a default KB with the proper directory structure if none exists.

    Returns the slug of the created KB, or None if KBs already exist.
    """
    # Check if any KBs exist (directories with .kb.json)
    if config.WIKI_ROOT.exists():
        for d in config.WIKI_ROOT.iterdir():
            if d.is_dir() and (d / ".kb.json").exists():
                logger.info("已有知识库: %s", d.name)
                return None

    slug = "main"
    kb_dir = config.WIKI_ROOT / slug
    now = datetime.now(timezone.utc).isoformat()

    # Create directory structure
    dirs = [
        kb_dir / "wiki" / "concepts",
        kb_dir / "wiki" / "summaries",
        kb_dir / "wiki" / "entities",
        kb_dir / "wiki" / "synthesis",
        kb_dir / "sources",
        kb_dir / ".trash",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        # .gitkeep so empty dirs survive git operations
        (d / ".gitkeep").touch(exist_ok=True)

    # .kb.json
    kb_meta = {
        "id": f"{slug}-default",
        "user_id": "local",
        "name": "主页",
        "slug": slug,
        "description": "默认知识库",
        "source_count": 0,
        "wiki_page_count": 3,
        "created_at": now,
        "updated_at": now,
    }
    (kb_dir / ".kb.json").write_text(
        json.dumps(kb_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Seed wiki pages
    (kb_dir / "wiki" / "index.md").write_text(
        "# Wiki Index\n\n## Entities (实体)\n\n## Concepts (概念)\n\n## Summaries (摘要)\n\n## Synthesis (综合)\n",
        encoding="utf-8",
    )
    (kb_dir / "wiki" / "overview.md").write_text(
        "# Wiki 知识概览\n\n"
        "> 最后更新: {bootstrap_date} | 页面: 0 | 源文档: 0\n\n"
        "## 知识版图\n\n"
        "_知识库刚初始化，尚无内容。待 ingest 首批文档后将自动填充。_\n\n"
        "## 概念网络\n\n"
        "_暂无概念。_\n\n"
        "## 知识空白与方向\n\n"
        "_等待首批文档 ingest 后识别。_\n".format(
            bootstrap_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        ),
        encoding="utf-8",
    )
    (kb_dir / "wiki" / "log.md").write_text(
        f"# 操作日志\n\n## [{datetime.now(timezone.utc).strftime('%Y-%m-%d')}] bootstrap | 初始化知识库\n"
        "- 创建默认知识库 `main`\n"
        "- 初始化 wiki 目录结构\n",
        encoding="utf-8",
    )

    # Initial git commit
    _git("add", "-A")
    _git("commit", "-m", f"bootstrap: 初始化知识库 main [agent v{config.VERSION}]")

    logger.info("已创建默认知识库: %s", slug)
    return slug


def find_pending_docs() -> list[tuple[str, str]]:
    """Scan all KBs and return (doc_id, reason) for docs needing ingest.

    reason: "new" — never ingested
            "updated" — source modified since last ingest
    """
    pending: list[tuple[str, str]] = []

    if not config.WIKI_ROOT.exists():
        return pending

    for kb_dir in sorted(config.WIKI_ROOT.iterdir()):
        if not kb_dir.is_dir():
            continue
        sources_dir = kb_dir / "sources"
        if not sources_dir.exists():
            continue

        for doc_dir in sorted(sources_dir.iterdir()):
            if not doc_dir.is_dir():
                continue
            doc_id = doc_dir.name
            doc_path = f"sources/{doc_id}/"

            # Check if current branch is master; skip if on an ingest branch
            # (don't scan while a previous ingest is unfinished)
            branch_result = _git("branch", "--show-current")
            if not branch_result or branch_result.returncode != 0:
                continue
            current_branch = branch_result.stdout.strip()
            if current_branch.startswith("ingest/") or current_branch.startswith("reingest/"):
                continue

            # Check if branch already exists (ingest in progress, needs review)
            branch_check = _git("branch", "--list", f"ingest/{doc_id}")
            if branch_check and branch_check.stdout.strip():
                continue  # branch exists, waiting for review

            branch_check = _git("branch", "--list", f"reingest/{doc_id}")
            if branch_check and branch_check.stdout.strip():
                continue

            # Has it been ingested before?
            last_ingest = _git(
                "log", "--oneline", "master", "--grep", f"ingest: {doc_id}", "--format=%H", "-1"
            )
            if not last_ingest or not last_ingest.stdout.strip():
                pending.append((doc_id, "new"))
                continue

            # Source updated since last ingest?
            last_ingest_hash = last_ingest.stdout.strip()
            last_source = _git(
                "log", "--oneline", "master", "--format=%H", "-1", "--", doc_path
            )
            if last_source and last_source.stdout.strip():
                if last_source.stdout.strip() != last_ingest_hash:
                    pending.append((doc_id, "updated"))

    return pending


# ── Ingest loop ────────────────────────────────────────────────


async def run_ingest(doc_id: str, reason: str) -> None:
    """Execute the full ingest workflow for one document."""

    kb_slug = _detect_kb(doc_id)
    if not kb_slug:
        log(f"⚠ 找不到 {doc_id} 所属的知识库，跳过")
        return

    branch = f"{'re' if reason == 'updated' else ''}ingest/{doc_id}"
    log(f"ingest 开始: {doc_id} ({reason})")
    _write_state(state="running", current_doc=doc_id, branch=branch, round=0,
                 extra={"reason": reason, "kb_slug": kb_slug})

    # ── 1. Ensure we start from a clean master ──
    _git("checkout", "master")

    # ── 2. Create the ingest branch ──
    # Delete existing branch if any (re-ingest case)
    existing = _git("branch", "--list", branch)
    if existing and existing.stdout.strip():
        _git("branch", "-D", branch)
    r = _git("checkout", "-b", branch)
    if not r or r.returncode != 0:
        log(f"✗ 无法创建分支 {branch}: {r.stderr if r else 'git 不可用'}")
        return
    log(f"  已创建分支: {branch}")

    provider = get_provider(config)
    tools = all_tools()

    # ── 3. Build initial message ──
    doc_path = f"{kb_slug}/sources/{doc_id}/"
    source_dir = config.WIKI_ROOT / doc_path

    file_list = []
    if source_dir.exists():
        for f in sorted(source_dir.iterdir()):
            if f.is_file():
                file_list.append(f"  {f.name} ({_format_size(f.stat().st_size)})")
    files_text = "\n".join(file_list) if file_list else "  (空目录)"

    task = "重新 ingest" if reason == "updated" else "ingest"
    today = datetime.now().strftime("%Y-%m-%d")
    user_msg = TextBlock(text=f"""请 {task} {kb_slug}/sources/{doc_id}/ 下的文档。

## 第一步：检查 .manifest.json

调用 **manifest** 工具读取 manifest（按 system prompt 第 1.5 节的决策树）：

```
manifest action="read" path="{kb_slug}/sources/{doc_id}"
```

manifest 不存在时工具会自动按文件名推断每个文件的角色（main/supplement/asset），返回推断结果但**不写盘**。根据角色决定本次要建/更新哪些 wiki 页。

## 第二步：读取文档

使用 **bash** 工具执行以下命令查看源文件：

```bash
ls -la {kb_slug}/sources/{doc_id}/
```

然后用 **read_file** 读取每个文件的内容（比 bash cat 更快更安全）：

```
read_file path="{kb_slug}/sources/{doc_id}/文件名"
```

## 后续步骤

1. 用 **read_file** 读取 {kb_slug}/wiki/overview.md — **这是你的记忆文件**，快速了解 wiki 知识全貌
2. 用 **read_file** 读取 {kb_slug}/wiki/index.md 查看现有页面清单
3. 用 **bash** `rg` 搜索 wiki 中是否已有相关概念（如 `rg -r '' "关键词" {kb_slug}/wiki/`）
4. 用 **write_file** 在 {kb_slug}/wiki/summaries/ 下创建摘要页
5. 用 **write_file** 重写 {kb_slug}/wiki/index.md（在第 2 步 read_file 的原内容基础上，在对应分类下插入新页面链接）
6. 用 **write_file** 重写 {kb_slug}/wiki/overview.md（按照 system prompt 中的格式模板：更新知识版图、概念网络、知识空白——这是你的持久记忆，不可跳过）
7. 用 **read_file** 读取 {kb_slug}/wiki/log.md，然后用 **write_file** 重写 {kb_slug}/wiki/log.md（在读取的原内容基础上追加新条目，日期用 "{today}"）
8. 用 **bash** 执行 git commit：
```bash
git add -A
git commit -m "ingest: {doc_id} — 文档标题

- 新增摘要: summaries/xxx.md
- 新增/更新概念: concepts/xxx.md
- 更新 index.md
- 更新 overview.md"
```

## 重要规则

- 知识库: **{kb_slug}**，所有 wiki 路径必须带 `{kb_slug}/` 前缀！
- 当前已在 git 分支 `{branch}` 上，无需切换分支。
- **log.md、index.md、overview.md 都用 write_file 整文件重写**，不要用 echo/printf/cat>> 等 shell 重定向追加
- **读取任何文本文件都用 read_file**，不要用 bash cat——read_file 更快更安全，且有行号便于定位
- **overview.md 是记忆中枢**，每次 ingest 必须更新其知识版图、概念网络、知识空白
- 日志条目中的日期直接写 "{today}"，不要用 $(date ...) 或任何 shell 命令替换
- **每一步都必须实际调用工具执行，不要只描述。现在开始第一步。**""")

    messages: list[Message] = [
        Message(role="user", content=[user_msg]),
    ]

    empty_commit_streak = 0  # Track consecutive "nothing to commit" results
    native_tool_used = False  # Once model uses native tool calling, stop aggressive fallback
    text_only_streak = 0  # Track consecutive text-only (non-tool) responses

    for round_num in range(1, config.MAX_TOOL_ROUNDS + 1):
        _write_state(state="running", current_doc=doc_id, branch=branch, round=round_num)
        response = await provider.chat(messages, tools)

        # Track usage
        if response.usage:
            log(f"  [round {round_num}] tokens: {response.usage.get('input_tokens', '?')} in / {response.usage.get('output_tokens', '?')} out")

        # Helper to check if a git commit result is empty (no changes)
        def _is_empty_commit(result: dict) -> bool:
            stdout = str(result.get("stdout", ""))
            stderr = str(result.get("stderr", ""))
            combined = stdout + stderr
            return ("nothing to commit" in combined or
                    "nothing added to commit" in combined or
                    result.get("exit_code") == 1)

        if not response.has_tool_calls():
            # No native tool calls — model is thinking between calls, or done.
            if native_tool_used:
                text_only_streak += 1
                if text_only_streak >= 3:
                    log(f"ingest 完成: {doc_id} — 连续 {text_only_streak} 次纯文本，视为完成")
                    break
                messages.append(response)
                log(f"  [round {round_num}] 纯文本（第{text_only_streak}次），继续等待...")
                continue
            # Model never used native tools — can't call tools, done
            log(f"ingest 完成: {doc_id} — {response.text[:200]}")
            break

        # Execute native tool calls
        native_tool_used = True  # Model is capable of native tool calling
        text_only_streak = 0  # Reset text-only counter
        messages.append(response)
        all_empty_commits = True
        for tc in response.tool_calls():
            log(f"  [{tc.tool_name}] {_summarize_input(tc.input)}")
            result = await execute_tool(
                tc.tool_name, tc.input,
                supports_images=provider.supports_images(),
            )
            # Track empty commits
            if tc.tool_name == "bash" and "git commit" in str(tc.input.get("command", "")):
                if not _is_empty_commit(result):
                    all_empty_commits = False
            else:
                all_empty_commits = False
            result_text = json.dumps(result, ensure_ascii=False, default=str)
            if len(result_text) > 5000:
                result_text = result_text[:5000] + "\n... (truncated)"
            messages.append(Message(
                role="user",
                content=[ToolResultBlock(
                    tool_use_id=tc.tool_id,
                    content=result_text,
                    is_error=("error" in str(result).lower()),
                )],
            ))
        if all_empty_commits:
            empty_commit_streak += 1
            if empty_commit_streak >= 2:
                log(f"  连续 {empty_commit_streak} 次空提交，任务可能已完成，提前结束")
                break
        else:
            empty_commit_streak = 0
    else:
        log(f"⚠ ingest {doc_id}: 达到最大轮数 ({config.MAX_TOOL_ROUNDS})，强制停止")

    # ── 4. Validate: did the model actually update the wiki? ──
    # Collect all changed files from TWO sources:
    #   a) git status --porcelain (uncommitted changes)
    #   b) git diff master --name-only (committed changes on this branch)
    changed_paths: set[str] = set()

    # (a) Uncommitted working-tree changes
    status_r = _git("status", "--porcelain")
    if status_r and status_r.stdout.strip():
        for line in status_r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            path = line[3:].strip().replace("\\", "/")
            changed_paths.add(path)

    # (b) Committed changes on this branch vs master
    diff_r = _git("diff", "master", "--name-only")
    if diff_r and diff_r.stdout.strip():
        for line in diff_r.stdout.strip().split("\n"):
            path = line.strip()
            if path:
                changed_paths.add(path)

    wiki_prefix = f"{kb_slug}/wiki/"
    modified_files: list[str] = []
    content_pages: list[str] = []
    index_updated = False
    log_updated = False
    overview_updated = False

    for path in sorted(changed_paths):
        if not path.startswith(wiki_prefix):
            continue  # Skip non-wiki changes (e.g. sources/)
        if not path.endswith(".md"):
            continue
        if path.endswith("/.gitkeep"):
            continue

        modified_files.append(path)
        # Extract parent dir name (e.g. "summaries" from "main/wiki/summaries/hello.md")
        dir_name = Path(path).parent.name
        if dir_name in ("summaries", "concepts", "entities", "synthesis"):
            content_pages.append(path)
        if Path(path).name == "index.md":
            index_updated = True
        if Path(path).name == "log.md":
            log_updated = True
        if Path(path).name == "overview.md":
            overview_updated = True

    # Validate required changes
    errors: list[str] = []
    if not content_pages:
        errors.append("未生成新的 wiki 内容页（summaries/concepts/entities/synthesis）")
    if not index_updated:
        errors.append("未更新 index.md（新页面需要在此注册）")

    if errors:
        for err in errors:
            log(f"  ✗ {err}")
        log(f"⚠ ingest 失败: {doc_id} — wiki 不完整，丢弃分支")
        _git("checkout", "-f", "master")
        _git("branch", "-D", branch)
        _write_state(state="error", extra={"last_doc": doc_id, "last_error": "; ".join(errors)})
        return

    log(f"  生成/修改了 {len(modified_files)} 个 wiki 文件:")
    for f in modified_files:
        marker = "✓" if (f in content_pages or f.endswith("/index.md") or f.endswith("/log.md") or f.endswith("/overview.md")) else "·"
        log(f"    {marker} {f}")
    if not log_updated:
        log(f"  ⚠ 未更新 log.md（建议追加操作记录）")
    if not overview_updated:
        log(f"  ⚠ 未更新 overview.md（建议更新知识版图记忆）")

    # ── 5. Auto-commit if model forgot and there are uncommitted changes ──
    status_r = _git("status", "--porcelain")
    if status_r and status_r.stdout.strip():
        log("  模型未 commit，自动提交...")
        _git("add", "-A")
        cmt = _git("commit", "-m", f"ingest: {doc_id} [agent v{config.VERSION}]")
        if cmt and cmt.returncode == 0:
            log("  已自动提交")
        else:
            log(f"  提交失败 (可能无变更): {cmt.stderr if cmt else ''}")

    # ── 6. Return to master ──
    _git("checkout", "-f", "master")
    _write_state(state="idle", extra={"last_doc": doc_id, "last_completed_at": datetime.now(timezone.utc).isoformat()})


def _detect_kb(doc_id: str) -> str | None:
    """Find which KB a doc_id belongs to."""
    for kb_dir in sorted(config.WIKI_ROOT.iterdir()):
        if not kb_dir.is_dir():
            continue
        if (kb_dir / "sources" / doc_id).exists():
            return kb_dir.name
    return None


def _summarize_input(inp: dict) -> str:
    """Short summary of a tool input for logging."""
    if "command" in inp:
        cmd = inp["command"]
        return cmd[:80] + ("..." if len(cmd) > 80 else "")
    if "path" in inp:
        return inp["path"]
    return ", ".join(f"{k}={str(v)[:40]}" for k, v in inp.items())


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


# ── Main loop ──────────────────────────────────────────────────


async def main() -> None:
    log("=" * 40)
    log(f"LLM Wiki Agent v{config.VERSION}")
    log(f"  WIKI_ROOT: {config.WIKI_ROOT}")
    log(f"  Provider: {config.PROVIDER} / {config.MODEL}")
    log(f"  扫描间隔: {config.SCAN_INTERVAL}s（API 触发的扫描可在 ~1s 内唤醒）")
    log(f"  日志: {config.LOG_FILE}")
    log(f"  Git: {config.GIT_USER_NAME} <{config.GIT_USER_EMAIL}>")
    log("=" * 40)

    setup_git()
    bootstrap_default_kb()
    _write_state(state="idle", extra={"started_at": datetime.now(timezone.utc).isoformat()})

    while True:
        # Consume any trigger file set while we were busy (race-during-ingest).
        # If the API wrote .scan_requested while we were ingesting, pick it up
        # now and force a re-scan even if no new docs are pending.
        triggered_now = _consume_trigger()

        try:
            pending = find_pending_docs()
            if pending:
                log(f"扫描: 发现 {len(pending)} 个待处理文档: {[d[0] for d in pending]}")
                for doc_id, reason in pending:
                    try:
                        await run_ingest(doc_id, reason)
                    except Exception as e:
                        log(f"✗ ingest 失败: {doc_id} — {e}")
                        logger.exception("ingest failed")
                        _write_state(state="error", extra={"last_doc": doc_id, "last_error": str(e)[:200]})
                        # Try to get back to master
                        _git("checkout", "-f", "master")
            else:
                if triggered_now:
                    log("扫描: 外部触发（无待处理文档）")
                else:
                    log(f"扫描: 无待处理文档")
                _write_state(state="idle")
        except Exception as e:
            log(f"扫描出错: {e}")
            logger.exception("scan failed")
            _write_state(state="error", extra={"last_error": str(e)[:200]})

        log(f"等待 {config.SCAN_INTERVAL}s（API 触发可提前唤醒）...")
        triggered_in_wait = await _wait_with_trigger(config.SCAN_INTERVAL)
        if triggered_in_wait:
            log("检测到外部触发，立即扫描")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Agent 已停止")
