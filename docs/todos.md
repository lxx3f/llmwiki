# LLM Wiki — 待办事项

> **进度**: 7/7 已完成 | 最近更新: 2026-07-01

---

## 🔴 高优先级

### 1. ~~Embedding 未接入 OCR 流水线~~ ✅ 已修复

- **修复内容**: 在 `api/services/chunker.py` 的 `_store_chunks_on_conn()` 中添加 embedding 自动生成
- **结果**: 所有 chunk 写入路径自动触发向量生成，Ollama 不可用时非致命降级

### 2. ~~QA 页面未接入 LLM 生成回答~~ ✅ 已修复

- **修复内容**:
  - 创建 `api/routes/qa.py`：`POST /v1/qa/ask` 端点，混合搜索（向量 + 全文 + ILIKE 降级）→ Ollama LLM → `{answer, sources}`
  - 在 `api/main.py` 中注册 qa 路由
  - 重写 `api/templates/qa.html`：使用 `marked` 库渲染 Markdown 回答，可折叠来源引用，聊天 UI
  - 在 `api/services/rag.py` 中添加 `_fallback_ilike()` 降级搜索
- **结果**: QA 页面从纯关键词搜索升级为真正的 RAG 智能问答

---

## 🟡 中优先级

### 3. ~~测试基础设施断裂~~ ✅ 已修复

- **修复内容**: 重写 `tests/helpers/schema.sql`（单用户 schema）、`tests/integration/conftest.py`（单用户架构），新增 12 个 KB CRUD 集成测试，`api/routes/knowledge_bases.py` 新增 `UniqueViolationError` → 409 处理
- **结果**: 28 个测试全部通过（16 单元 + 12 集成）

### 4. ~~export-to-wiki skill 未实现~~ ✅ 已修复

- **修复内容**: 创建/完善 4 个 wiki 维护 skills：
  - `.claude/skills/ingest.md` — 读源 → 摘要 → 更新 index → 更新关联页 → 追加 log
  - `.claude/skills/query.md` — wiki 页面优先查询，不足时回退 RAG
  - `.claude/skills/lint.md` — 健康检查：矛盾/孤立/过时/缺失
  - `.claude/skills/export-to-wiki.md` — 对话知识导出到 wiki
- **MCP 改进**: `search` 工具新增 `scope` 参数（`wiki`/`sources`/`all`），支持按 wiki 页面或源文档范围搜索
- **CLAUDE.md**: 新增 index.md/log.md 格式约定、wiki 目录结构规范、skills 工作流说明
- **结果**: wiki 编译和维护责任移交 Claude Code agent 层，通过 skills 定义工作流，通过 MCP 工具获得读写能力

---

## 🟢 低优先级

### 5. ~~CSS 死文件清理~~ ✅ 已修复

- **修复内容**: 删除 `api/static/css/` 下 5 个已合并到 `app.css` 的文件，清理 `.claude/settings.json` 过期权限
- **结果**: `api/static/css/` 仅保留 `app.css`

### 6. ~~前端双重存在~~ ✅ 已解决

- **解决方式**: 移除 `web/`（Next.js 16, 84 文件）及 `netlify.toml`，统一为 `api/templates/`（Jinja2, 8 模板）
- **结果**: 单一前端方案，删除 ~10,000 行冗余代码

### 7. ~~TUS 上传状态内存存储~~ ✅ 已修复

- **修复内容**: 在 `api/infra/tus.py` 中实现文件系统元数据持久化（`_save_metadata`/`_delete_metadata`/`_recover_uploads`），`api/main.py` lifespan 中调用 `init_tus_uploads()`
- **结果**: 服务器重启后 TUS 上传状态完整保留，支持断点续传
