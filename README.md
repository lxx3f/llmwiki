# LLM Wiki

[![License](https://img.shields.io/badge/license-Apache%202.0-green)](https://opensource.org/licenses/Apache-2.0)

Agent 驱动的个人知识库，基于文件系统 + Git。核心理念来自 [Karpathy LLM Wiki](https://x.com/karpathy/status/2039805659525644595)：**Agent 全权拥有 wiki 层**。

你精选信息源、提好问题；Agent 负责阅读、总结、交叉引用、保持一致性。知识在 Git 仓库中累积，每步都可追溯可审核。

## 三层架构

| 层级 | 谁操作 | 说明 |
|------|--------|------|
| **sources/**（原始文档） | 你 | PDF、文章、笔记、图片。你放入 + `git commit`，Agent 只读。 |
| **wiki/**（知识页面） | Agent | Agent 生成和维护的 .md 页面——摘要、概念、实体、交叉引用。你只读。 |
| **Schema**（CLAUDE.md / .claude/skills/） | 你 + Agent | 共同演化的工作流契约。Agent 的纪律来源。 |
| **Git**（版本 & 审核） | 你 + Agent | Agent 在分支上提交，你在 Web 界面 review diff 后 merge/拒绝。 |

Agent 与你**职责分明**：你提供原材料 + 最终决策，Agent 做中间所有繁琐的"记账"工作——交叉引用更新、摘要同步、矛盾检测。

## 系统组成

```
┌─────────────────────────────────────────────────────────┐
│  Agent 后台进程 (agent/run.py)                          │
│  ─ 扫描 sources/ → 发现新/更新文档                       │
│  ─ Provider 适配：Anthropic / OpenAI 兼容 / Ollama       │
│  ─ 7 个工具：bash / read_file / write_file / edit_file   │
│    view_image / manifest / extract_pdf / lint            │
│  ─ 在 ingest/{doc_id} 分支 git commit，触发人工审核       │
└─────────────────────────────────────────────────────────┘
                       │ 写 wiki/ + commit
                       ▼
┌─────────────────────────────────────────────────────────┐
│  WIKI_ROOT/  (Git 仓库，可指向 Obsidian vault)            │
│  ├── main/                                              │
│  │   ├── .kb.json         知识库元数据                   │
│  │   ├── wiki/            Agent 维护（你只读）           │
│  │   │   ├── overview.md  ★ Agent 记忆中枢               │
│  │   │   ├── index.md     内容目录                       │
│  │   │   ├── log.md       操作日志                       │
│  │   │   └── summaries/ concepts/ entities/ synthesis/  │
│  │   ├── sources/         你维护（Agent 只读）           │
│  │   │   └── 004__efficient-loftr/                      │
│  │   │       ├── .manifest.json   ★ 文件角色元数据        │
│  │   │       └── EfficientLoFTR.pdf                     │
│  │   └── .trash/          软删除                         │
└─────────────────────────────────────────────────────────┘
                       │ 只读
                       ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI 展示层 (api/main.py)                            │
│  /             知识库列表                                │
│  /wiki/{slug}  wiki 页面浏览 + 源文件预览                 │
│  /review       审核 Agent 分支变更                        │
│  /agent        Agent 监控面板（HTMX 5s 自动刷新）         │
│  /v1/qa        RAG 问答（ripgrep + Ollama）              │
│  /settings     Wiki 根目录 + 系统设置                     │
└─────────────────────────────────────────────────────────┘
```

**零依赖存储**——不依赖 PostgreSQL、pgvector、任何数据库。Git 提交历史是唯一的元数据。

## 工作流

### 1. 新增文档 → manifest 决策 → ingest

```bash
mkdir -p main/sources/004__efficient-loftr/
cp ~/Downloads/EfficientLoFTR.pdf main/sources/004__efficient-loftr/
git add main/sources/004__efficient-loftr/ && git commit -m "add source"
```

Agent 启动时（每 60s）扫描 `sources/`，发现新文档后：

1. **读 `.manifest.json`** —— 文件角色分类（`main`/`supplement`/`asset`）。缺失则按文件名启发式推断
2. **PDF → `extract_pdf` 工具** —— 输出到 `.cache/extract/<doc_id>.md`，按页分节，支持增量读取
3. **读 `overview.md`** —— Agent 的记忆中枢，2 秒了解 wiki 全貌
4. **写 wiki 页面** —— summaries/concepts/entities，按需新建或更新
5. **更新 index/log/overview** —— 整文件重写
6. **git commit 在 `ingest/004__xxx` 分支** —— 等待审核

### 2. 更新文档 → 自动 re-ingest

```bash
# 替换源文件
git add main/sources/004__efficient-loftr/ && git commit -m "update"
```

Agent 比较 `last_ingest_hash` vs `last_source_hash`，不一致则触发 re-ingest 在 `reingest/004__xxx` 分支。

### 3. 审核

打开 http://localhost:8000/review：

- 看每个分支的 commit message + diff stat
- 点进看完整 diff（master vs 分支）
- **批准** → merge 到 master 并删除分支
- **拒绝** → 删除分支

### 4. 健康检查 → lint

Agent 调用 `lint` 工具做 5 项检查：

- `stats` — 页面/源文档统计
- `orphans` — 无入站引用的孤立页面
- `outdated` — 源文件比最后 ingest commit 新的文档
- `unindexed` — 存在但 index.md 没列出的页面
- `contradiction_ctx` — 核心概念在多页面的提及片段（LLM 判断是否真矛盾）

结果写入 `<kb>/wiki/synthesis/health-report-<date>.md`，由用户在审核界面批准。

## Agent 监控

http://localhost:8000/agent — 实时状态仪表盘：

- **状态徽章**：idle / running / error / stale（>5 分钟无更新 = 可能僵死）
- **当前任务**：doc_id + 分支 + 轮次
- **KB 指标**：每个 KB 的源文档数 + wiki 页面数
- **待处理文档**：尚未 ingest 的 doc 列表
- **最近历史**：git log 中的 ingest commits
- **日志尾**：agent.log 最后 30 行，HTMX 5s 自动刷新

Agent 写 `agent/.state.json`（idle/running/error + current_doc + branch + round），api 端点读取后渲染。

## Git 作为状态机

文档生命周期完全由 Git 追踪，没有 `.meta.json`：

```bash
# 是否已 ingest？
git log --oneline --grep="ingest: 001__my-paper"

# 是否需要 re-ingest？
last_ingest=$(git log master --grep="ingest: 001__my-paper" --format=%H -1)
last_source=$(git log master --format=%H -1 -- main/sources/001__my-paper/)
[ "$last_source" != "$last_ingest" ] && echo "needs re-ingest"
```

文件级检测（manifest 机制）：一个 doc_dir 内有多个文件时，`.manifest.json` 标注每个的角色：

```json
{
  "doc_id": "005__paper",
  "files": {
    "paper.pdf":                  {"role": "main"},
    "appendix-supplementary.md":  {"role": "supplement"},
    "images/fig1.png":            {"role": "asset"}
  }
}
```

Agent 据此决定：main → 摘要页；supplement → 合并到主摘要；asset → 仅在 wiki 中嵌入引用。

## 快速开始

### 前提

- Python 3.11+
- Git
- [Ollama](https://ollama.com/)（默认 LLM）或 Anthropic API key
- 可选：[LibreOffice](https://www.libreoffice.org/)（Office 文档转换）

### 1. 克隆 & 安装

```bash
git clone <repo> && cd llmwiki
pip install -r api/requirements.txt
pip install -r agent/requirements.txt
```

### 2. 配置 `.env`

项目根创建 `.env`：

```bash
WIKI_ROOT=C:\path\to\your\wiki       # 你的 wiki 目录（可指向 Obsidian vault）
OLLAMA_URL=http://localhost:11434
LLM_MODEL=qwen2.5:14b
```

### 3. 启动展示层

```bash
cd api
python -m uvicorn main:app --reload --port 8000
```

打开 http://localhost:8000

### 4. 启动 Agent（可选）

```bash
cd agent
python run.py
```

Agent 每 60s 扫描一次 sources/。首次启动会自动创建默认 KB 结构（`main/`）。

不启动 Agent 也可以——你随时手动 `/ingest <doc_id>` 触发；Agent 只是把这件事自动化 + 后台化。

### 5. 用 Obsidian 浏览（可选）

把 `WIKI_ROOT` 目录作为 vault 用 Obsidian 打开，获得链接预览 + 图视图 + 双向链接。

## Agent Skills（`.claude/skills/`）

| Skill | 触发 | 功能 |
|-------|------|------|
| `ingest` | `/ingest` 或 Agent 自动扫描 | manifest 决策 → extract_pdf → 写 wiki → commit |
| `lint` | `/lint` 或 Agent 周期检查 | 5 项健康检查 + 写报告到 `synthesis/` |
| `query` | 用户提问 | 先查 wiki 页面 → 不足时 RAG 搜索源文档 |
| `export-to-wiki` | "导出到 wiki" | 对话内容识别知识点 → 写入 wiki |

## Agent Tools

| 工具 | 替代了 | 说明 |
|------|--------|------|
| `bash` | shell | 命令执行，自动 `cd WIKI_ROOT` |
| `read_file` | `cat` | 增量读取（offset/limit），比 cat 更快更安全 |
| `write_file` | `cat > file` | 整文件写入（创建或覆盖） |
| `edit_file` | `sed` | 精确字符串替换（old_text 须唯一匹配） |
| `view_image` | — | 多模态模型用图片 base64 |
| `manifest` | 启发式命名 | 显式声明文件角色，避免误判 |
| `extract_pdf` | `python -c "from pdf_oxide..."` | 可复用 PDF 提取，输出 `.cache/extract/` |
| `lint` | ripgrep + git log | wiki 健康检查（stats/orphans/outdated/unindexed/contradiction_ctx） |

## 为什么有效

维护知识库最繁琐的不是阅读或思考，而是"记账"：更新交叉引用、保持摘要不过时、标注矛盾。Agent 不会无聊、不会忘记——**维护成本趋近于零**。Git 让每次变更可追溯、可回滚、可审核。

三层架构（sources/wiki/schema）的边界让**权责清晰**：你只负责原材料 + 最终决策，Agent 负责中间所有繁琐工作。每层都可以独立替换——换 LLM 不影响存储结构，换存储不影响 LLM 行为。

## License

Apache 2.0