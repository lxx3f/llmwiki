# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

LLM Wiki 是一个单用户本地知识库系统，核心理念对应三层架构：

- **原始文档（Raw Sources）**: 用户上传的 PDF、文章、笔记、图片、表格等。这些文件一旦上传就不可变——LLM 可以读取但绝不修改。这是知识的源头。
- **Wiki 页面（The Wiki）**: LLM 生成和维护的 markdown 文件，包括摘要、概念页、对比页、综合页。LLM 全权拥有这一层：创建页面、在新文档到来时更新、维护交叉引用、保持一致性。用户只读；LLM 负责写。
- **Schema 文件（The Schema）**: 本文件（CLAUDE.md）告诉 LLM wiki 的结构、约定和工作流。它让 LLM 成为有纪律的 wiki 维护者而非泛泛的聊天机器人。用户和 LLM 在使用过程中共同演化这个文件。

技术栈：
- **API** (`api/`): FastAPI 后端，处理文档上传/处理/OCR、知识提取、Jinja2 模板渲染
- **Agent** (`agent/`): 后台常驻进程，扫描 `sources/` 自动 ingest 到 wiki 目录，git 追踪变更
- **存储**: 纯文件系统（`api/services/filestore.py` — JSON 元数据 + Markdown 内容），无数据库依赖
- **搜索**: ripgrep 全文搜索（`subprocess.run(['rg', ...])`），不再依赖 pgvector/PGroonga
- **AI**: Ollama 本地模型，默认 `qwen2.5:14b`

## 常用命令

### API 后端

```bash
cd api
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8021
```

### Agent 后台进程

```bash
cd agent
pip install -r requirements.txt
python run.py
```

扫描 `sources/` 目录，对未 ingest / 源更新的文档执行 wiki 写入 → git commit。详见「服务化部署（NSSM）」小节。

### 测试

```bash
# 运行所有测试（无需数据库——测试在临时目录中创建 FileStore）
pytest -v

# 运行单个测试文件
pytest tests/unit/test_chunker.py -v
```

CI 通过 `.github/workflows/test.yml` 自动运行。

## 服务化部署（NSSM）

本项目在 Windows 上通过 [NSSM](https://nssm.cc/) 把两个组件注册为 Windows 服务，实现**开机自启 + 崩溃自动重启 + 后台常驻**。

### 一次性环境准备

下载 NSSM（任选一种来源，路径无所谓，install 脚本会自动检测）：
- 官网稳定版：<https://nssm.cc/release/nssm-2.24.zip> → 解压到 `C:\Tools\nssm-2.24\`
- GitHub 最新版：<https://github.com/nssmcc/nssm/releases> → 解压到 `C:\Tools\nssm-win64-Release\`

**可选**：加入 PATH（不加入也能用，install 脚本会自动探查常见路径）：
```powershell
# PowerShell 管理员
setx PATH "$env:PATH;C:\Tools\nssm-win64-Release"   # GitHub 版
# 或
setx PATH "$env:PATH;C:\Tools\nssm-2.24\win64"        # 官网版
```

**Install 脚本的 NSSM 搜索顺序**（找不到时报错并提示）：
1. `-NssmPath` 参数显式传入
2. `nssm.exe` 在 PATH 中
3. 常见安装路径（覆盖 9 种布局，含 `C:\Tools\nssm-win64-Release\nssm.exe`）

### 安装/卸载服务

所有脚本在 `scripts/` 目录下：

| 脚本 | 用途 | 权限 |
|------|------|------|
| `scripts/install_services.ps1` | 注册 `LlmWikiApi` + `LlmWikiAgent` 两个服务 | 管理员（自动提权） |
| `scripts/uninstall_services.ps1` | 停止并删除两个服务 | 管理员（自动提权） |
| `scripts/start.bat` | 手动启动两个服务 | 普通用户 |
| `scripts/stop.bat` | 手动停止两个服务 | 普通用户 |
| `scripts/restart.bat` | 手动重启两个服务 | 普通用户 |
| `scripts/status.bat` | 查看服务状态 + 健康检查 | 普通用户 |
| `scripts/tail-logs.bat` | 尾部查看 4 个日志文件 | 普通用户 |

**首次安装**（PowerShell 管理员）：
```powershell
cd C:\Users\23236\repositories\llmwiki
.\scripts\install_services.ps1
```

可选参数：
```powershell
.\scripts\install_services.ps1 -ApiPort 9000
.\scripts\install_services.ps1 -PythonPath "D:\Python312\python.exe"
.\scripts\install_services.ps1 -NssmPath "C:\Tools\nssm-win64-Release\nssm.exe"
```

**卸载**（PowerShell 管理员）：
```powershell
.\scripts\uninstall_services.ps1
# 同样支持 -NssmPath 覆盖
.\scripts\uninstall_services.ps1 -NssmPath "C:\Tools\nssm-win64-Release\nssm.exe"
```

### NSSM 配置细节（`install_services.ps1` 写入）

| 参数 | 值 | 作用 |
|------|-----|------|
| `AppDirectory` | `api/` 或 `agent/` | 工作目录——决定 `.env` 加载、相对路径解析 |
| `AppStdout` / `AppStderr` | `logs/<svc>.{out,err}.log` | stdout/stderr 重定向到日志 |
| `AppRotateFiles` | `1` | 启用日志轮转 |
| `AppRotateBytes` | `10485760` | 单文件上限 10MB |
| `Start` | `SERVICE_AUTO_START` | **开机自启** |
| `AppExit` | `Default Restart` | 崩溃后自动重启 |
| `AppRestartDelay` | `5000` | 重启延迟 5 秒 |
| `AppThrottle` | `5000` | 防止崩溃循环（5 秒内不再启动） |

### 关键约定

- **API 服务启动命令去掉了 `--reload`**：NSSM 服务环境会破坏文件监视器，且生产用 hot-reload 不合适
- **Agent 启动目录是 `agent/`**：`run.py` 里有 `STATE_FILE = Path(__file__).resolve().parent / ".state.json"`，必须从 agent 目录运行
- **两个服务的 `AppDirectory` 都指向各自子目录**：`api/config.py` 和 `agent/config.py` 用 `Path(__file__).parent` 定位 `.env`，把工作目录放对是 `.env` 加载的前提

### 故障排查

1. **服务起不来**：看 `logs/<svc>.err.log`（NSSM 启动失败的根因通常在这里）
2. **Agent 不工作**：看 `logs/agent.err.log` + `agent/.state.json`（`state: "error"` 字段包含 `last_error`）
3. **端口冲突**：`netstat -ano | findstr :8021` → 找到占用进程
4. **NSSM 命令速查**：
   ```powershell
   nssm start LlmWikiApi
   nssm stop LlmWikiApi
   nssm restart LlmWikiApi
   nssm status LlmWikiApi
   nssm edit LlmWikiApi    # 打开 GUI 编辑
   nssm get LlmWikiApi AppDirectory  # 查询参数
   ```
5. **彻底重装**：先 `uninstall_services.ps1` 再 `install_services.ps1`

### 与开发模式的区别

| 维度 | 开发模式 | 服务模式 |
|------|---------|---------|
| 启动方式 | `python -m uvicorn main:app --reload` | NSSM 包装，无 `--reload` |
| 日志位置 | 控制台 | `logs/api.out.log` / `logs/api.err.log` |
| 工作目录 | 终端当前目录（一般是 `api/`） | NSSM 设置的 `AppDirectory`（也是 `api/`） |
| `.env` 加载 | `cd api` 后启动 | NSSM 启动时 `AppDirectory=api` 即可 |
| 代码修改 | 自动热重载 | 需 `scripts/restart.bat` 才生效 |

## 架构关键概念

### FileStore 存储层（`api/services/filestore.py`）

纯文件系统数据访问层，替代原来的 PostgreSQL。目录结构：

```
WIKI_ROOT/                              # 默认 ./wiki_data/，可指向 Obsidian vault
├── {kb_slug}/                          # 每个知识库 = 一个目录
│   ├── .kb.json                        # KB 元数据（name, slug, description, created_at, updated_at）
│   ├── wiki/                           # Wiki 页面（LLM 拥有的 .md 文件）
│   │   ├── index.md                    # 内容目录（LLM 维护）
│   │   ├── overview.md                 # 全局概览
│   │   ├── log.md                      # 操作日志
│   │   ├── concepts/
│   │   ├── summaries/
│   │   ├── entities/
│   │   └── synthesis/
│   ├── sources/                        # 源文档（不可变的原始文件）
│   │   └── {doc_number:03d}__{safe_name}/
│   │       ├── source.{ext}            # 原始上传文件（不可变）
│   │       ├── .meta.json              # 元数据（name, type, status, tags, created_at, updated_at）
│   │       ├── content.md              # 提取/处理后的 Markdown 文本
│   │       ├── pages/                  # 多页文档（{page:03d}.md）
│   │       └── images/                 # 嵌入图片
│   └── .trash/                         # 软删除目录
├── .users.json                         # 单用户配置
└── .extractions/                       # 提取任务队列（{task_id}.json）
```

**核心原则：**
- 文件系统是唯一数据源——没有数据库
- Wiki 页面 = `.md` 文件，git 可追踪
- 源文档 = 不可变原始文件 + `.meta.json` 元数据
- 搜索 = ripgrep（文件名 + 内容全文搜索）
- 原子写入：先写临时文件 → `os.replace()` 重命名
- 文档 ID = `{doc_number:03d}__{safe_name}`（天然唯一、可排序、可读）
- 软删除：移动到 `.trash/` 目录

**FileStore 关键方法：**
| 分类 | 方法 |
|------|------|
| KB | `list_kbs()`, `get_kb(slug)`, `create_kb()`, `update_kb()`, `delete_kb()` |
| 文档 | `list_docs(kb_slug)`, `get_doc()`, `get_doc_by_path()`, `create_doc()`, `update_doc_content()`, `delete_doc()` |
| 源文件 | `create_source_doc()`, `store_source_file()`, `get_source_path()`, `get_doc_content()` |
| 搜索 | `search(kb_slug, query, scope, max_results)` — 调用 ripgrep |
| 工具 | `next_doc_number()`, `safe_filename()`, `slugify()` |

### 认证模型（单用户模式）

单用户本地模式，无 JWT 验证：

- `api/auth.py`: `get_current_user()` 直接返回 `app.state.effective_user_id`
- `api/deps.py`: 两个依赖——`get_store()`、`get_user_id()`
- 启动时 `api/main.py` 的 lifespan 调用 `store.get_or_create_user()` 自动创建单用户

### Agent 与 Skills 工具

Claude Code 通过 skills（`.claude/skills/*.md`）执行 wiki 维护——**直接在文件系统 + Git 上操作**，不再走 MCP 工具转发：

- `agent/run.py` — 后台常驻主循环，扫描 `sources/` → 创建 git 分支 → 调用 LLM（带 `agent/tools/` 工具）→ 自动 commit → 回到 master
- `agent/providers/` — 适配 Anthropic / OpenAI 兼容 / Ollama 三种 LLM 后端
- `agent/tools/` — agent 可调用的工具：`read_file` / `write_file` / `bash` / `manifest` 等
- `api/agent_monitor.py` — API 侧读取 `agent/.state.json` + 日志，驱动 `/agent` 监控仪表盘

wiki 写入的语义规则、index.md / log.md / overview.md 的维护约定见下文「Wiki 维护工作流（通过 Skills）」。

### 文档处理管道（`api/services/ocr.py`）

上传文档的状态流转：`pending` → `processing` → `ready`（或 `failed`）。状态存储在 `.meta.json` 的 `status` 字段。

`OCRService` 类通过 `asyncio.Semaphore(3)` 控制并发，按文件类型分发处理：

| 文件类型 | 处理方式 |
|---------|---------|
| **PDF** | 默认 `pdf-oxide`（本地 Rust 库，免费），可选 Mistral OCR API（需 `MISTRAL_API_KEY`，设置 `PDF_BACKEND=mistral`） |
| **HTML** | `api/html_parser/parser.py` 自定义解析器 → Markdown + 标记 HTML，支持图片内嵌（含 SSRF 防护） |
| **图片 (png/jpg/webp/gif)** | 直接存储，不做 OCR |
| **表格 (xlsx/csv)** | openpyxl 解析，每个 sheet 作为一个 `document_page`，渲染为 Markdown 表格 |
| **Markdown/TXT** | 直接读取、分块、存储 |

处理结果：提取文本 → `content.md`，分页 → `pages/{page:03d}.md`，嵌入图片 → `images/`。

文档处理完成后自动触发知识提取（创建 `.extractions/{task_id}.json`）。

### 文本分块（`api/services/chunker.py`）

所有文档内容经 `chunk_text()`/`chunk_pages()` 分块。参数：~512 token/块，~128 token 重叠，最小 32 token。块会追踪 markdown 标题面包屑（`heading_breadcrumbs`），用于搜索结果上下文显示。

分块结果不再存入数据库，而是写入源文档目录下的文件供搜索使用。

### 搜索（ripgrep 全文搜索）

QA 和 search 工具通过 `FileStore.search()` 调用 ripgrep 进行全文搜索：
- 搜索范围：wiki/ 目录（.md 文件）+ sources/ 的 content.md
- 支持 `-i` 大小写不敏感、`-C` 上下文行
- 不再依赖向量搜索（pgvector）或 PGroonga 索引

### QA 问答系统（`api/routes/qa.py`）

RAG 问答管道：`POST /v1/qa/ask` 接收 `{kb_id, question, top_k}` →
1. `FileStore.search()` ripgrep 全文搜索 wiki/ + sources/
2. 构造上下文 prompt，调用 Ollama LLM（`settings.LLM_MODEL`）综合生成自然语言回答
3. 返回 `{answer, sources}` — Markdown 格式回答 + 来源片段列表
4. 前端 `qa.html` 使用 `marked` 库渲染 Markdown，展示可折叠来源引用

### 知识提取系统（`api/services/extraction.py` + `api/routes/extraction.py`）

半自动知识提取反馈闭环：

1. 文档处理完成 → 自动创建 `.extractions/{task_id}.json`（状态 `pending`）
2. 用户在 Web 界面"待提取"列表看到待处理项
3. 点击运行提取 → `ExtractionService` 调用 Ollama（默认 `qwen2.5:14b`）分析文档
4. LLM 返回 JSON（Markdown 内容 + 建议标签）
5. 用户在审核页审阅、修改 → 批准（正式写入 wiki/ 目录下的 .md 文件）或拒绝

### Wiki 维护工作流（通过 Skills）

Karpathy LLM Wiki 的核心理念：**LLM 全权拥有 wiki 层**。Claude Code 通过 skills（`.claude/skills/*.md`）执行 wiki 维护，直接在文件系统 + Git 上操作。

**Skills vs Commands 命名空间**：
- `.claude/skills/*.md` — **上下文触发**（Claude 按 description 匹配用户意图自动调用）
- `.claude/commands/*.md` — **显式斜杠命令**（用户输入 `/name` 调用）

| Skill / Command | 类型 | 功能 | 触发 |
|------------------|------|------|------|
| `ingest` | skill | 读源 → 摘要 → 更新 index → 更新关联页 → 追加 log | `/ingest` 或用户说要处理新文档 |
| `query` | skill | 先读 index → wiki 页面 → 不足时回退 RAG → 好答案归档 | 用户提问时 |
| `lint` | skill | 健康检查：矛盾/孤立/过时/缺失报告 | `/lint` |
| `export-to-wiki` | skill | 对话内容 → 识别知识点 → 写入 wiki | 用户说"导出到 wiki" |
| `wrap-up` | **command** | 总结本次会话改动、检查/更新 README/CLAUDE.md/skills | `/wrap-up`（手动） |

#### 核心约定：index.md 和 log.md

两个特殊文件帮助 LLM 导航 wiki（由 LLM 自动维护，用户只读）：

**index.md** (`/wiki/index.md`) — 内容目录，每次 compose/ingest 后 LLM 自动更新。格式：
```markdown
# Wiki Index

## Entities (实体)
- [DETR](wiki/concepts/DETR.md) — End-to-End Object Detection with Transformers (2020)

## Concepts (概念)
- [Attention Mechanism](wiki/concepts/attention.md) — 注意力机制原理与变体

## Summaries (摘要)
- [Paper Notes: DETR](wiki/summaries/detr-paper.md) — DETR 论文要点

## Synthesis (综合)
- [Object Detection Landscape](wiki/synthesis/object-detection.md) — 目标检测方法对比
```

**log.md** (`/wiki/log.md`) — 操作时间线，追加式记录，格式：
```markdown
## [2026-07-01] ingest | DETR 论文
- 新增摘要页: [summaries/detr-paper.md](summaries/detr-paper.md)
- 更新概念页: attention, transformer
- 发现: End-to-end detection without NMS
```

#### Wiki 目录结构约定

```
/wiki/
  index.md          ← LLM 维护的内容目录
  log.md            ← LLM 维护的操作日志
  overview.md       ← wiki 全局概览/当前认知状态
  summaries/        ← 源文档摘要
  concepts/         ← 概念解释页
  entities/         ← 实体/人物/产品页
  synthesis/        ← 综合/对比/分析页
```

### 标签系统（`api/routes/tags.py`）

平面标签，多对多关联：
- 标签存储在 `.meta.json` 的 `tags` 数组中 + YAML frontmatter
- API 支持标签 CRUD + 文档打标/去标 + 按标签浏览文档
- Web 界面：`/tags` 页面管理标签

### API 路由结构

所有路由在 `api/main.py` 中注册：

**REST API 路由**（JSON 响应）：
| 路由模块 | 前缀 | 说明 |
|---------|------|------|
| `routes/health.py` | `/health` | 健康检查 |
| `routes/knowledge_bases.py` | `/v1/knowledge-bases` | KB CRUD |
| `routes/documents.py` | `/v1/knowledge-bases/{kb_id}/documents`, `/v1/documents/{doc_id}` | 文档 CRUD、内容更新、批量删除 |
| `routes/me.py` | `/v1/me` | 用户信息 |
| `routes/tags.py` | `/v1/tags` | 标签 CRUD + 文档打标 |
| `routes/extraction.py` | `/v1/extractions` | 提取任务管理 |
| `routes/files.py` | `/files/{doc_id}/{subpath}` | 本地文件访问 |
| `routes/qa.py` | `/v1/qa` | RAG 问答（ripgrep + LLM 综合回答） |
| `infra/tus.py` | `/v1/uploads` | TUS 可恢复上传协议 |

**Jinja2 页面路由**（HTML 响应，在 `api/main.py` 中直接定义）：
| 路径 | 模板 | 说明 |
|------|------|------|
| `/` | `index.html` | 知识库列表 + 创建 |
| `/wikis/{slug}` | `wiki_detail.html` | Wiki 详情（侧边栏 + 文档阅读器 + wiki 内容） |
| `/tags` | `tags.html` | 标签管理 |
| `/extractions` | `extraction.html` | 待提取任务列表 |
| `/extractions/{task_id}` | `extraction_review.html` | 提取审核 |
| `/qa` | `qa.html` | 问答界面 |
| `/agent` | `agent.html` | Agent 监控仪表盘（HTMX 5s 自动刷新） |
| `/agent/log` | `agent_log_partial.html` | HTMX partial：主日志末尾（`?tail=N&level=all|warn|error`） |
| `/agent/errors` | `agent_log_partial.html` | HTMX partial：errors 日志末尾（仅 WARNING+ERROR，`?tail=N`） |
| `/agent/history` | `agent_history_partial.html` | HTMX partial：最近 ingest commits |
| `/settings` | `settings.html` | 系统状态 + Wiki 根目录设置 |

**Agent 状态端点**（JSON）：
| 路径 | 说明 |
|------|------|
| `/v1/agent/status` | 状态 + KB 列表 + 待处理 + 最近历史 |

> 注意：CLAUDE.md 中其他路由模块（`routes/health.py` 等）是大重构前的旧结构，实际已不存在。完整路由见 `api/main.py`。

### Agent 日志系统

Agent 双文件日志（`agent/run.py:37-78`），写在 `LOG_DIR`（默认 `./logs/`，相对项目根）下：

| 文件 | 内容 | 轮转 | 保留 |
|------|------|------|------|
| `agent.log` | INFO/DEBUG 活动日志 | 每天午夜（`%Y-%m-%d`） | 7 份（约 1 周） |
| `agent.errors.log` | WARNING+ERROR（**独占**，不与主日志重复） | 每周一（`%Y-W%W`） | 4 份（约 1 个月） |

实现用 `logging.handlers.TimedRotatingFileHandler`。**主 handler 加了 `addFilter(lambda r: r.levelno < logging.WARNING)`** 排除 WARNING+——让 errors 文件**独占**严重级别，监控面板 `/agent/errors` 拿到的就是干净的错误信号。

**writer（agent）** 和 **reader（`api/agent_monitor.py`）** 都从同一组 env 解析路径，writer/reader 一致——否则滚动后 reader 会找不到文件。

监控面板 `/agent` 把日志分两个区域：
- "近期活动"（主日志，每 5s 刷新）
- "错误/警告"（errors 文件，每 10s 刷新）

### 前端技术栈

主要 UI 通过 Jinja2 模板（`api/templates/`）+ Tailwind CDN + Alpine.js + HTMX 渲染：
- 布局：`base.html` 定义侧边栏（5 个导航项）+ 主内容区
- CSS：单一合并文件 `api/static/css/app.css`，Typewriter 主题，48 个 CSS 自定义属性
- 上传：TUS 协议 + `api/static/js/upload.js`
- Jinja2 自定义过滤器：`format_date`（处理 ISO 字符串和 datetime 对象）

### 环境变量

配置文件：api 和 agent 都读项目根目录的 `.env`。详见 `.env.example`。

核心变量（`api/config.py` 中 `Settings` 类定义）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI_ROOT` | `./wiki_data/` | Wiki 文件系统根目录（可指向 Obsidian vault） |
| `SINGLE_USER_ID` | `local` | 单用户模式的用户 ID |
| `STORAGE_ROOT` | `./data/files/` | TUS 上传临时文件存储路径 |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API 地址 |
| `LLM_MODEL` | `qwen2.5:14b` | 知识提取/问答 LLM |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding 模型（可选，QA 已改为 ripgrep） |
| `EMBEDDING_DIM` | `768` | 向量维度 |
| `PDF_BACKEND` | `pdf_oxide` | PDF 处理引擎（`pdf_oxide` 或 `mistral`） |
| `MISTRAL_API_KEY` | `""` | Mistral OCR API 密钥（仅 PDF_BACKEND=mistral 时需要） |
| `STAGE` | `dev` | 部署环境（dev/production） |
| `APP_URL` | `http://localhost:8021` | API 自身 URL（CORS 白名单） |
| `API_URL` | `http://localhost:8021` | API 自身 URL |
| `AGENT_LOG_DIR` | `./logs/` | Agent 日志目录（相对项目根，可设绝对路径） |
| `AGENT_LOG_FILE` | `<LOG_DIR>/agent.log` | 主日志文件名（自动追加 `.YYYY-MM-DD` 后缀轮转） |
| `AGENT_LOG_ERROR_FILE` | `<LOG_DIR>/agent.errors.log` | 错误日志文件名（轮转后缀 `.YYYY-Www`） |
| `AGENT_LOG_BACKUPS` | `7` | 主日志保留份数（约 1 周） |
| `AGENT_LOG_ERROR_BACKUPS` | `4` | 错误日志保留份数（约 1 个月） |
| `AGENT_LOG_LEVEL` | `INFO` | 全局最低日志级别（DEBUG/INFO/WARNING/ERROR） |
| `LOGFIRE_TOKEN` | `""` | Logfire 可观测性（可选） |
| `SENTRY_DSN` | `""` | Sentry 错误追踪（可选） |

## 常见陷阱与可复用模式

以下是从 PostgreSQL → FileStore 迁移过程中积累的实战经验。

### 1. JSON 存储的 datetime 陷阱

**问题**：从数据库迁移到 JSON 文件存储后，`created_at`/`updated_at` 从 Python `datetime` 对象变成 ISO 字符串（如 `"2026-07-01T12:34:56.789Z"`）。模板中调用 `.strftime()` 会抛出：

```
jinja2.exceptions.UndefinedError: 'str object' has no attribute 'strftime'
```

**解决**：注册 Jinja2 自定义 `format_date` 过滤器，同时处理 ISO 字符串和 datetime 对象（`api/main.py:126-138`）：

```python
from datetime import date, datetime

def _format_date(value, fmt="%Y-%m-%d"):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return value[:10]  # 粗略截取
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return str(value)

templates.env.filters["format_date"] = _format_date
```

模板中使用 `{{ doc.created_at | format_date }}` 替代 `{{ doc.created_at.strftime(...) }}`。

**教训**：任何 JSON 序列化的日期字段，在模板中不要假设它是 datetime 对象。统一用过滤器包装。

### 2. HTTP Header Latin-1 编码限制

**问题**：Starlette/Uvicorn 要求 HTTP 响应头值必须是 Latin-1（ISO 8859-1）可编码的。含中文字符的 header 值导致：

```
UnicodeEncodeError: 'latin-1' codec can't encode characters in position ...
```

**根因**：`_safe_filename()` 中 `re.sub(r'[^\w\-.]', ...)` 的 `\w` 在 Python 3 中匹配 Unicode 字母（包括中文），中文字符未被替换，最终出现在 `X-Document-Id` header 中。

**解决**：对 header 值使用 `urllib.parse.quote(value, safe="/")`（`api/infra/tus.py:369`）：

```python
from urllib.parse import quote as _url_quote

headers["X-Document-Id"] = _url_quote(document_id, safe="/")
```

中文字符会被 URL 编码（如 `测试文档` → `%E6%B5%8B%E8%AF%95%E6%96%87%E6%A1%A3`），编码后全是 ASCII，Latin-1 安全。

### 3. `\w` 正则的 Unicode 陷阱

Python 3 中 `\w` 匹配所有 Unicode 字母/数字/下划线（包括中文、日文等），不像 Python 2 只匹配 `[a-zA-Z0-9_]`。如果需要 ASCII-only 安全文件名，使用显式字符类：

```python
# ❌ 中文字符不会被替换
safe = re.sub(r'[^\w\-.]', '_', name)

# ✅ 只保留 ASCII 字母数字
safe = re.sub(r'[^a-zA-Z0-9\-_.]', '_', name)
```

### 4. 运行时热更新 FileStore

单用户本地应用无需重启即可切换数据目录（`api/main.py:277-317`）：

```
PATCH /v1/settings { wiki_root: "/new/path" }
  1. 验证路径
  2. 写 .env 文件持久化（更新 WIKI_ROOT= 行）
  3. settings.WIKI_ROOT = new_path     # 更新运行时配置
  4. FileStore(new_path)               # 创建新实例
  5. request.app.state.store = new_store  # 热替换
```

适用于：前端设置页更改 wiki 根目录、切换到 Obsidian vault 等场景。注意：切换后旧 FileStore 实例不再有效，所有后续请求使用新实例。

### 5. 前端调用本地文件选择器

通过后端 API 暴露 tkinter 原生对话框（`api/main.py:258-274`）：

- **后端**：`POST /v1/settings/browse-directory` → `tkinter.Tk()` + `filedialog.askdirectory()`
- **前端**：`<button>` → `fetch('/v1/settings/browse-directory')` → 填入 `<input>`
- **关键**：`root.attributes("-topmost", True)` 确保对话框在浏览器窗口前面
- **注意**：此方案仅适用于本地运行的应用（tkinter 需要图形环境，服务器部署不可用）

### 6. `.env` 文件写入模式

`PATCH /v1/settings` 更新 `.env` 时采用行替换而非全量重写：

```python
# 读取 → 逐行检查 → 替换或追加 → 写回
lines = env_text.splitlines()
new_lines = []
found = False
for line in lines:
    if line.startswith("DATABASE_URL="):
        continue  # 删除已废弃的 key
    if line.startswith("WIKI_ROOT="):
        new_lines.append(f"WIKI_ROOT={new_value}")
        found = True
    else:
        new_lines.append(line)
if not found:
    new_lines.append(f"WIKI_ROOT={new_value}")
```

保留注释和其他配置，只修改目标行。同时可以顺便清理已废弃的配置项（如 `DATABASE_URL`）。

### 7. Jinja2 模板中使用 `| e` 过滤器防止 XSS

在 JS 代码中嵌入变量时，使用 Jinja2 的 `| e` 过滤器：

```javascript
// ❌ kb.name 含特殊字符会破坏 JS 语法
onclick="confirmDelete('{{ kb.id }}', '{{ kb.name }}')"

// ✅ 安全转义
onclick="confirmDelete('{{ kb.id }}', '{{ kb.name | e }}')"
```
