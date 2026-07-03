# LLM Wiki

[![License](https://img.shields.io/badge/license-Apache%202.0-green)](https://opensource.org/licenses/Apache-2.0)

Agent 驱动的个人知识库，基于文件系统 + Git。核心理念来自 [Karpathy LLM Wiki](https://x.com/karpathy/status/2039805659525644595)：**Agent 全权拥有 wiki 层**。

你精选信息源、提好问题；Agent 负责阅读、总结、交叉引用、保持一致性。知识在 Git 仓库中累积，每步都可追溯可审核。

## 三层架构

| 层级 | 谁操作 | 说明 |
|------|--------|------|
| **sources/**（原始文档） | 你 | PDF、文章、笔记。你放入 + `git commit`，Agent 只读。 |
| **wiki/**（知识页面） | Agent | Agent 生成和维护的 .md 页面——摘要、概念、实体、交叉引用。 |
| **Git**（版本&审核） | 你 + Agent | Agent 在分支上提交，你在 Web 界面 review diff 后 merge/拒绝。 |

## 架构

```
Agent (Claude Code / OpenClaw / NanoBot)
  │  内置能力: 文件读写, ripgrep, Git, Ollama, pdf-oxide
  │  Skills:   ingest, query, lint
  │
  ▼  直接操作文件系统 + Git

WIKI_ROOT/  (Git 仓库)
  ├── my-kb/
  │   ├── wiki/          Agent 维护
  │   │   ├── index.md    内容目录
  │   │   ├── log.md      操作日志
  │   │   ├── summaries/  源文档摘要
  │   │   ├── concepts/   概念页
  │   │   ├── entities/   实体页
  │   │   └── synthesis/  综合/对比
  │   └── sources/        你维护
  │       └── 001__my-paper/
  │           └── source.pdf

  │
  ▼  只读

Web 展示层 (~200 行 FastAPI)
  • /wiki/{slug}  浏览渲染后的 .md 页面
  • /review       审核 Agent 的 Git 分支变更
```

**零依赖存储**——不依赖 PostgreSQL、pgvector 或任何数据库。Git 提交历史是唯一的元数据。**Agent 不需要 MCP 服务器**——自带文件操作能力，直接读写 WIKI_ROOT。

## 工作流

### 新增文档 → ingest

```bash
mkdir -p sources/001__my-paper/
cp ~/Downloads/paper.pdf sources/001__my-paper/source.pdf
git add sources/001__my-paper/
git commit -m "add: my-paper"
```

Agent 通过 `git log --diff-filter=A` 发现新文档，在 `ingest/{doc_id}` 分支上生成 wiki 页面。

### 更新文档 → re-ingest + lint

```bash
# 替换 source.pdf 为新版本
git add sources/001__my-paper/
git commit -m "update: my-paper v2"
```

Agent 检测到源文件 commit 晚于最后 ingest commit，自动 re-ingest 并 lint。

### 审核

打开 Web 审核页面，看 git diff，批准（merge）或拒绝（删除分支）。

## Git 作为状态机

没有 `.meta.json`。文档生命周期完全由 Git 追踪：

```
新增  → git log --diff-filter=A → ingest
更新  → 对比 source commit vs ingest commit → re-ingest
删除  → git log --diff-filter=D → 标记过时
```

```bash
# 是否已 ingest？
git log --oneline --grep="ingest: 001__my-paper"

# 是否需要 re-ingest？
last_ingest=$(git log --oneline --grep="ingest: 001__my-paper" --format="%H" -1)
last_source=$(git log --oneline --format="%H" -1 -- sources/001__my-paper/)
# 哈希不同 → 源已更新
```

## 快速开始

### 前提

- Python 3.11+
- Git
- [Ollama](https://ollama.com/)（Agent 调 LLM 用）

### 1. 创建 Wiki 目录

```bash
mkdir -p ~/my-wiki/my-kb/wiki/{summaries,concepts,entities,synthesis}
mkdir -p ~/my-wiki/my-kb/sources
cd ~/my-wiki && git init
echo "# Wiki Index" > my-kb/wiki/index.md
echo "# Log" > my-kb/wiki/log.md
git add -A && git commit -m "init"
```

### 2. 启动展示层

```bash
cd api
pip install -r requirements.txt
echo "WIKI_ROOT=$(cd ~/my-wiki && pwd)" > .env
python -m uvicorn main:app --reload --port 8000
```

### 3. 用 Obsidian 浏览

用 Obsidian 打开 WIKI_ROOT，完整浏览体验包括链接预览和图视图。

### 4. Agent 连接

Agent 直接访问 WIKI_ROOT 目录。Claude Code 打开该目录即可使用 `/ingest`、`/lint` 等 skill。

## Agent Skills

`.claude/skills/` 定义了 Agent 的自动化工作流：

| Skill | 触发 | 功能 |
|-------|------|------|
| `ingest` | `/ingest` 或自动扫描 | 读取 sources/ → 摘要/概念/实体页 → 更新 index + log |
| `lint` | `/lint` | 矛盾检测、孤立页面、过时内容、缺失交叉引用 |
| `query` | 提问时 | 优先查 wiki 页面 → 不足时搜索源文档 |

## 为什么有效

维护知识库最繁琐的不是阅读或思考，而是"记账"：更新交叉引用、保持摘要不过时、标注矛盾。Agent 不会无聊、不会忘记——**维护成本趋近于零**。Git 让每次变更可追溯、可回滚、可审核。

## License

Apache 2.0
