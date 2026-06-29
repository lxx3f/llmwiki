# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

LLM Wiki 是一个开源的知识库系统，让用户上传文档（PDF、文章、笔记等），然后通过 Claude（MCP 连接）来阅读、搜索、编写 wiki 页面。核心思想：原始文档不可变（Claude 只读），wiki 页面由 Claude 维护、交叉引用和更新。

三层架构：
- **Web** (`web/`): Next.js 16 前端，提供仪表盘、PDF/HTML 阅读器、wiki 渲染器
- **API** (`api/`): FastAPI 后端，处理认证、上传、文档处理、OCR
- **MCP** (`mcp/`): MCP 服务器，向 Claude 暴露 search/read/write/delete 工具
- **Converter** (`converter/`): 隔离的 LibreOffice 服务，负责 office→PDF 转换
- **数据库**: Supabase (PostgreSQL + RLS + PGroonga 全文搜索)

## 常用命令

### Web 前端

```bash
cd web
npm install          # 安装依赖
npm run dev          # 开发服务器（Turbopack，端口 3000）
npm run build        # 生产构建
npm run start        # 生产启动
```

### API 后端

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### MCP 服务器

```bash
cd mcp
pip install -r requirements.txt
uvicorn server:app --reload --port 8080
```

### 数据库（本地开发）

```bash
docker compose up -d                                # 启动 PostgreSQL（端口 5432）
docker compose -f docker-compose.test.yml up -d     # 启动测试数据库（端口 5434）
psql "$DATABASE_URL" -f supabase/migrations/001_initial.sql  # 运行迁移
```

### 测试

```bash
# 运行所有测试（需要先启动测试数据库 docker compose -f docker-compose.test.yml up -d）
pytest -v

# 运行单个测试文件
pytest tests/unit/test_chunker.py -v

# 运行特定测试类
pytest tests/integration/isolation/test_api_isolation.py::TestReadIsolation -v
```

测试需要本地 PostgreSQL（端口 5434，数据库 `supavault_test`）。CI 通过 `.github/workflows/test.yml` 自动运行。

## 架构关键概念

### 认证模型（双路径）

API 使用两种数据库访问模式：

1. **读操作** → `ScopedDB`（`api/deps.py:24`）。在事务中执行 `SET LOCAL ROLE authenticated` + `SET LOCAL request.jwt.claims`，依赖 Supabase RLS 策略自动过滤行。用于 SELECT 路由。
2. **写操作** → 直接使用 `asyncpg.Pool`，在 SQL WHERE 子句中显式传递 `user_id`（如 `WHERE id = $X AND user_id = $Y`）。用于 INSERT/UPDATE/DELETE 路由。

JWT 验证通过 Supabase auth 的 JWKS 端点（`api/auth.py`），支持 ES256 算法。MCP 服务器也有独立的 token 验证器（`mcp/auth.py`）。

### MCP 工具系统

5 个工具注册在 `mcp/tools/__init__.py`：
- `guide` — 列出可用的 knowledge bases 和理解 wiki 工作流
- `search` — `list` 模式浏览文件，`search` 模式通过 PGroonga `&@~` 操作符全文搜索
- `read` — 单文件或 glob 批量读取（120k 字符预算），PDF 分页读取，内嵌图片
- `write` — `create`（新建页面）、`str_replace`（精确文本替换）、`append`（追加）
- `delete` — 按路径或 glob 归档文档

MCP 数据库访问也分两种：`scoped_*` 函数（带 RLS）用于 SELECT，`service_*` 函数（绕过 RLS）用于写入。

### 文档处理管道（`api/services/ocr.py`）

上传文档的状态流转：`pending` → `processing` → `ready`（或 `failed`）。

按文件类型分发处理：
- **PDF**: 默认使用 `pdf-oxide`（免费、本地提取），可选 Mistral OCR API（需 `MISTRAL_API_KEY`，通过 `PDF_BACKEND=mistral` 切换）
- **Office (pptx/docx 等)**: LibreOffice 转为 PDF → 然后按 PDF 处理。可通过 `CONVERTER_URL` 指向独立的 converter 服务
- **HTML**: 使用自定义解析器（`api/html_parser/parser.py`）转 Markdown + 标记 HTML
- **图片**: 直接存储，不做 OCR
- **表格 (xlsx/csv)**: 用 openpyxl 解析，每个 sheet 作为 document_page 存储

### 文本分块（`api/services/chunker.py`）

所有文档内容最终都经过 `chunk_text()`/`chunk_pages()` 分块后存入 `document_chunks` 表。参数：~512 token/块，~128 token 重叠，最小 32 token。块会追踪 markdown 标题面包屑，用于搜索结果上下文显示。

### API 路由结构

读路由使用 `get_scoped_db` 依赖（RLS），写路由使用 `get_user_id` 依赖（显式 user_id 校验）：
- `/v1/knowledge-bases` — KB CRUD（`api/routes/knowledge_bases.py`）
- `/v1/documents` — 文档 CRUD、内容更新、批量删除（`api/routes/documents.py`）
- `/v1/me` — 用户信息（`api/routes/me.py`）
- `/v1/usage` — 用量统计（`api/routes/usage.py`）
- TUS 上传通过 `/upload/` 端点（`api/infra/tus.py`），支持断点续传

### Web 前端路由结构

Next.js App Router，使用路由组：
- `(auth)/` — 登录、注册、OAuth 回调
- `(dashboard)/` — 知识库主界面：`/wikis`（列表）、`/wikis/[slug]/[...path]`（文档浏览）、`/settings`、`/onboarding`
- `/oauth/authorize` — MCP OAuth 授权端点
- 全局状态用 Zustand（`web/src/stores/`），三个 store：`useUserStore`、`useKBStore`、`useSidebarStore`

### 数据库关键设计

- `documents` 表使用软删除（`archived` 字段），不物理删除
- 全文搜索使用 PGroonga 索引（`idx_chunks_content_pgroonga`）
- RLS 策略只允许用户访问自己的数据
- `handle_new_user()` 触发器在 Supabase auth 用户创建时自动同步到 `public.users`
- `document_number` 通过 advisory lock 生成每个 KB 内的自增编号
- 所有表有 `updated_at` 自动更新触发器

### 环境变量

配置文件读取路径：api 读 `../.env`，mcp 也读 `../.env`，web 读 `.env.local`。详见 `.env.example`。关键注意点：
- `SUPABASE_JWT_SECRET` 仅在旧的 HS256 项目需要，默认使用 Supabase 的 JWKS 端点
- 没有配置 S3 凭证时 OCR 服务不启动（`api/main.py:54`）
