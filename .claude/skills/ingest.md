---
name: ingest
description: 将 sources/ 中的源文档处理为 wiki 页面——读源、写摘要、更新索引、交叉引用、Git 分支审核
---

# Ingest 技能

触发条件：用户说 "ingest"、"处理文档"、"消化一下" 等，或对 Agent 说 "扫描待处理文档"。

## 核心理念

ingest 是 LLM Wiki 最核心的工作流。不只是索引一个文件——是把新知识融合进已有知识体系。一个源文档可能触及 5-15 个 wiki 页面。

**三层架构：**
- **Sources（原始文档）**: 用户上传的 PDF、文章、笔记、图片、表格等。**不可变**——LLM 可读但绝不修改
- **Wiki（LLM 拥有）**: markdown 页面（summaries/concepts/entities/synthesis），LLM 全权写，用户只读
- **Schema（CLAUDE.md）**: 本文件 + 父 CLAUDE.md，定义 wiki 的结构和工作流

所有变更是通过 **Git 分支** 提交的，用户审核后方可合并。Agent 永远不在 master 分支上直接操作 wiki。

## 重要：所有路径必须带知识库前缀

WIKI_ROOT 下可以有多个知识库（如 `main/`）。**所有文件操作都必须带知识库前缀**。

例如知识库为 `main` 时：
- 源文件在 `main/sources/{doc_id}/`
- Wiki 页面在 `main/wiki/summaries/`, `main/wiki/concepts/` 等
- Index 在 `main/wiki/index.md`
- Log 在 `main/wiki/log.md`
- **Overview 在 `main/wiki/overview.md`** — 这是 Agent 的记忆文件，每次 ingest 必读必写

任务指令中会明确告知本次的知识库名和各目录的完整路径，严格使用它们。

## wiki 目录约定

```
{kb}/wiki/
├── overview.md     知识全景记忆（每次 ingest 必更新）★
├── index.md        内容目录（按 Summaries/Concepts/Entities/Synthesis 分类）
├── log.md          操作日志（每次 ingest 追加一条记录）
├── summaries/      源文档摘要
├── concepts/       概念解释页
├── entities/       实体/人物/产品页
└── synthesis/      综合/对比/分析页
```

## overview.md — Agent 的记忆中枢

overview.md 是 Agent 跨会话的持久记忆。每次 ingest：
- **开始前必读** — 快速了解 wiki 全貌的入口
- **完成后必写** — 将本次 ingest 新增的知识归档到记忆中

overview.md 的格式：

```markdown
# Wiki 知识概览

> 最后更新: {日期} | 页面: {总页面数} | 源文档: {源文档数}

## 知识版图

### {领域1}
- **已有知识**: 用 2-3 句话概括 wiki 中这个领域的认知
- **关键概念**: [[concepts/xxx]] — 一句话说明
- **来源文档**: [[summaries/xxx]] — 带来了什么知识增量
- **覆盖度**: 🟢 深入 / 🟡 入门 / 🔴 仅涉及

### {领域2}
...

## 概念网络

用文字或简单的 ASCII 图描述概念之间的关联：
- [[concepts/A]] ← [[concepts/B]] (B 依赖 A)
- [[concepts/A]] → 可对比 → [[concepts/C]] (相似但不同场景)

## 知识空白与方向

- **明确空白**: 哪些领域/问题尚未覆盖
- **可疑矛盾**: 跨文档的不一致之处（如有）
- **建议深挖**: 哪些主题值得进一步补充
```

## 工作流程

### 阶段 1: 确认目标 + 扫描源文件

用 `ls main/sources/{doc_id}/` 列出源文件，确定文件类型（PDF、Markdown、图片等）。

### 阶段 1.5: 读取 .manifest.json（**必做**）

调用 **manifest 工具** `read_manifest` 读取 `main/sources/{doc_id}/.manifest.json`：
- 如果不存在 → 工具会**自动按文件名启发式推断**（不写盘），告诉你每个文件的角色
- 文件角色：
  - `main` — 主文档，可能生成新摘要页
  - `supplement` — 补充材料，**合并到主摘要，不独立成页**
  - `asset` — 图片/附件，**不写 wiki 页、不进摘要**，必要时在 wiki 里用 `![[filename]]` 嵌入

**决策时刻**：读完 manifest 后回答以下问题
- Q1: 有几个 `main` 文件？
  - 0 个（如 doc 里全是图片）→ 跳过摘要，只更新相关概念/实体页
  - 1 个 → 标准流程：建/更新 1 个 summaries 页
  - ≥2 个 → 每个 main **单独**建一个 summaries 页（除非主题重复）
- Q2: 有 `supplement` 吗？
  - 把它们**合并到主摘要的"补充材料"或"附录"段**，不独立建页
- Q3: 有 `asset` 吗？
  - 不写 wiki 页，**仅记录**到主摘要的"参考资源"段（如 `![[fig1.png]]`）
- Q4: 主题是否已在 wiki 中有专门页面（如 summaries/xxx.md）？
  - 是 → **更新**已有摘要（保留结构，追加新内容），不建新页
  - 否 → 走标准流程建新页

**首次 ingest 时**：调用 `write_manifest` 把决策结果**持久化**到 .manifest.json（之后 ingest 会自动读取）。
**不写盘也无妨**：manifest 缺失时下次会重新推断。

### 阶段 2: 创建审核分支

```bash
git checkout master
git checkout -b ingest/{doc_id}
```

所有变更在此分支上进行。绝不直接修改 master。**Agent 会自动处理分支创建和最后的 checkout master，你不需要手动操作。**

### 阶段 3: 读取源文档

**Markdown/文本文件**：用 `read_file` 工具直接读
```
read_file path="main/sources/{doc_id}/source.md"
```

**PDF 文件**（**用 extract_pdf 工具，不要手写 python**）：
```
extract_pdf pdf_path="main/sources/{doc_id}/filename.pdf"
```
- 工具内部用项目 Python 跑 `agent/scripts/extract_pdf.py`，结果写到 `<WIKI_ROOT>/.cache/extract/<doc_id>.md`
- 输出文件按页分节（`# Page 1`、`# Page 2` ...），用 `read_file` `offset`/`limit` 增量读：
  - `read_file path=".cache/extract/<doc_id>.md" offset=1 limit=200` 读前 200 行
  - `read_file path=".cache/extract/<doc_id>.md" offset=201 limit=200` 读下 200 行
- **不要自己写 extract.py / _dump.py / _fulltext.md 之类的临时文件**——用 extract_pdf 工具，输出位置固定
- 如果 PDF 太大，可以用 `max_pages` / `start_page` 分段提取

**图片**：用 `view_image` 工具查看。

### 阶段 4: 理解现有 wiki 状态

**先用 read_file 读 overview.md** — 这是 Agent 的记忆入口，2 秒了解 wiki 全貌

用 `read_file` 读 `main/wiki/index.md` 了解页面清单

用 bash 跑 `rg` 搜索相关关键词：
```bash
rg -i "<关键词>" main/wiki/
```

用 `read_file` 读 `main/wiki/log.md` 了解最近的变更

### 阶段 5: 与用户讨论关键要点（可选）

对于重要/复杂的文档，先向用户报告：
- 核心观点是什么
- 有哪些值得提取的概念、实体
- 与现有 wiki 有无冲突或补充

小文档可以直接进入阶段 6。

### 阶段 6: 生成 wiki 页面

**摘要页** (`main/wiki/summaries/`):
- 用 `write_file` 创建
- 内容要点：来源信息、核心观点、关键论据、方法论、局限性
- **必须在开头注明来源**

**概念页** (`main/wiki/concepts/`):
- 对文档中出现的每个重要概念，创建或更新概念页
- 用 `write_file` 创建新页；用 `write_file` **整文件重写**已存在的页面（追加新来源的信息）
- 在页面中标注哪些源文档提到了这个概念

**实体页** (`main/wiki/entities/`):
- 对重要人物、产品、组织，创建或更新实体页

**页面规范**:
- 使用 `[[双括号链接]]` 建立页面间的交叉引用（如: `[[concepts/transformer]]`）
- 标题层级: `##` 用于主节，`###` 用于子节
- 可以用 ` ```mermaid ` 绘制图表

### 阶段 7: 更新 index.md（必须）

- 先用 `read_file` 读取 `main/wiki/index.md`
- 用 `write_file` 整文件重写 index.md（在读取的原内容基础上，在对应分类下插入新页面链接）
- **不要用 edit_file**，write_file 整文件重写更可靠
- **这一步不可跳过**——所有新页面必须注册到 index.md

### 阶段 8: 更新 overview.md（必须）

**这一步不可跳过**——overview.md 是 Agent 跨会话的记忆，每次 ingest 必须归档。

- 先用 `read_file` 读取 `main/wiki/overview.md`
- 用 `write_file` 整文件重写 overview.md，按上述格式模板更新以下部分：
  - **知识版图**: 判断新文档属于哪个领域，用 2-3 句话更新该领域的"已有知识"摘要
  - **概念网络**: 如果新增了概念页，记录概念之间的依赖/对比关系
  - **知识空白**: 如果文档中提到但未深入的主题，或与已有知识的潜在矛盾，记录下来
- 如果文档开启了一个全新的领域，在"知识版图"中新增该领域条目
- 更新页面计数和源文档计数

### 阶段 9: 追加 log.md（必须）

- 先用 `read_file` 读取 `main/wiki/log.md`
- 用 `write_file` 整文件重写 log.md（在读取的原内容基础上追加新条目）
- 日期直接用具体日期字符串（如 "2026-07-06"），**绝对不要用 `$(date ...)` 命令替换**
- 格式示例：

```markdown
# 操作日志

## [2026-07-04] bootstrap | 初始化知识库
- ...

## [2026-07-06] ingest | 文档标题
- 新增摘要: summaries/xxx.md
- 新增概念: concepts/xxx.md
- 更新 index.md
```

### 阶段 10: 检查清单（提交前确认）

- [ ] 至少生成/更新了一个内容页（summaries/concepts/entities/synthesis）
- [ ] index.md 已更新，包含新页面的链接
- [ ] **overview.md 已更新**（知识版图 + 概念网络 + 知识空白）
- [ ] log.md 已追加操作记录

### 阶段 11: 提交

```bash
git add -A
git commit -m "ingest: {doc_id} — {文档标题}

- 新增摘要: summaries/xxx.md
- 更新概念: concepts/xxx.md
- 更新 index.md
- 更新 overview.md（如有）"
```

Agent 会自动处理分支创建和最后的 checkout master，你不需要手动操作。

## 工具使用原则

| 操作 | 工具 |
|------|------|
| 读取文件内容 | **read_file**（比 bash cat 更快更安全） |
| 目录浏览、git 操作、PDF 提取、rg 搜索 | **bash** |
| 创建新 wiki 页面 | **write_file** |
| 修改已有页面（index.md、log.md、概念页等） | **write_file**（整文件重写，最可靠） |
| 查看图片内容 | **view_image** |
| 文件角色判定 | **manifest**（read/write/infer） |
| PDF 文本提取 | **extract_pdf**（不要手写 python 脚本） |

## 重要提醒

- 所有路径都必须带知识库前缀，不要写裸的 `wiki/` 或 `sources/`
- 你已经在 ingest 分支上，直接工作即可，不要切换分支
- **用 edit_file 前必须先用 read_file 读取文件**——肉眼看到的格式和实际内容可能不一致
- edit_file 的 old_text 必须精确匹配，注意缩进和换行。从 read_file 输出中直接复制文本片段
- **如果 edit_file 返回错误**（匹配失败/匹配多次），立即用 read_file 重新读文件，从 read_file 输出中找到正确的文本，再次调用 edit_file——不要放弃
- 所有页面的创建和修改都用 write_file（整文件重写比 edit_file 更可靠，无需担心精确匹配问题）
- **log.md、index.md、overview.md 必须用 write_file 重写**，禁止用 bash echo/printf/cat>> 等 shell 重定向追加
- **PDF 提取：用 `extract_pdf` 工具**（已集成到工具集，脚本在 `agent/scripts/extract_pdf.py`），不要自己写 `extract.py` / `python -c "from pdf_oxide..."`
- **不要把临时文件写到 sources/ 目录**（如 `_fulltext.md` / `_dump.py` / `err.log`）—— extract_pdf 的输出在 `.cache/extract/<doc_id>.md`，不会污染源目录
- **不要输出 JSON 代码块来描述你计划做的操作**——直接调用工具执行。每一步都要实际产生效果

## Re-ingest（源文档更新后）

当源文档有新版本时，在 `reingest/{doc_id}` 分支上：

1. 读新版本源文件
2. 读现有相关 wiki 页面
3. 对比分析：新内容是否与旧断言矛盾？
4. 更新摘要页、受影响的概念/实体页
5. 在 log.md 记录变更
6. 提交：`git commit -m "reingest: {doc_id} v2 — 摘要更新"`

## 示例

用户: "ingest 004__efficient-loftr"

Agent 执行:
```
1. ls main/sources/004__efficient-loftr/
   → EfficientLoFTR.pdf
2. manifest action="read" path="main/sources/004__efficient-loftr"
   → { "files": [{"name": "EfficientLoFTR.pdf", "role": "main"}] }
3. extract_pdf pdf_path="main/sources/004__efficient-loftr/EfficientLoFTR.pdf"
4. read_file path=".cache/extract/004__efficient-loftr.md" 增量读 PDF 内容
5. read_file path="main/wiki/overview.md"  → 了解 wiki 全貌
6. read_file path="main/wiki/index.md"  → 页面清单
7. rg 搜索 "attention|transformer|matching" main/wiki/  → 检查已有概念
8. write_file path="main/wiki/summaries/efficient-loftr.md"  → 创建摘要
9. write_file path="main/wiki/concepts/efficient-loftr.md"  → 新建概念
10. write_file path="main/wiki/concepts/loftr.md"  → 新建前置概念
11. write_file path="main/wiki/concepts/transformer.md"  → 追加新来源
12. write_file path="main/wiki/index.md"  → 注册新页面
13. write_file path="main/wiki/overview.md"  → 更新知识版图
14. write_file path="main/wiki/log.md"  → 追加操作记录
15. git add -A && git commit -m "ingest: 004__efficient-loftr — EfficientLoFTR 论文"
```
