---
name: ingest
description: 将 sources/ 中的源文档处理为 wiki 页面——读源、写摘要、更新索引、交叉引用、Git 分支审核
---

# Ingest 技能

触发条件：用户说 "ingest"、"处理文档"、"消化一下" 等，或对 Agent 说 "扫描待处理文档"。

## 核心理念

ingest 是 LLM Wiki 最核心的工作流。不只是索引一个文件——是把新知识融合进已有知识体系。一个源文档可能触及 5-15 个 wiki 页面。

所有变更是通过 **Git 分支** 提交的，用户审核后方可合并。Agent 永远不在 master 分支上直接操作 wiki。

## 发现待处理文档

### 列出所有待处理源文档

```bash
# 列出 sources/ 下的所有目录
ls -d sources/*/

# 对每个目录，检查是否有对应的 ingest commit
for dir in sources/*/; do
  doc_id=$(basename "$dir")
  if ! git log --oneline master --grep="ingest: $doc_id" | grep -q .; then
    echo "待处理: $doc_id"
  fi
done
```

### 发现已更新需要 re-ingest 的文档

```bash
# 对已 ingest 的文档，检测源文件是否有新 commit
for dir in sources/*/; do
  doc_id=$(basename "$dir")
  last_ingest=$(git log --oneline master --grep="ingest: $doc_id" --format="%H" -1)
  if [ -z "$last_ingest" ]; then continue; fi
  last_source=$(git log --oneline master --format="%H" -1 -- "$dir")
  if [ "$last_source" != "$last_ingest" ]; then
    echo "需要 re-ingest: $doc_id (源已更新)"
  fi
done
```

## 工作流程

### 阶段 1: 确认目标

用户可能：
- 指定一个源文档目录（如 "ingest 001__my-paper"）
- 让 Agent 扫描所有待处理文档

用 `ls sources/` 或 Glob 列出源文件，确认目标文档存在且可读。

### 阶段 2: 创建审核分支

```bash
git checkout -b ingest/{doc_id}
```

所有变更在此分支上进行。绝不直接修改 master。

### 阶段 3: 读取源文档

对 Markdown/文本文件直接用 Read：
```
Read sources/001__my-paper/source.md
```

对 PDF 文件用 pdf-oxide：
```bash
python -c "
from pdf_oxide import PdfDocument
doc = PdfDocument('sources/001__my-paper/source.pdf')
for i in range(doc.page_count()):
    print(doc.to_markdown(i))
"
```

### 阶段 4: 理解现有 wiki 状态

```bash
# 查看 wiki 目录结构
ls -R wiki/

# 查看索引和日志
cat wiki/index.md
cat wiki/log.md

# 搜索相关已有内容
rg -i "<关键词>" wiki/
```

这一步很关键——写新内容之前必须知道 wiki 里已经有什么。

### 阶段 5: 与用户讨论关键要点（可选）

对于重要/复杂的文档，先向用户报告：
- 核心观点是什么
- 有哪些值得提取的概念、实体
- 与现有 wiki 有无冲突或补充

小文档可以直接进入阶段 6。

### 阶段 6: 生成 wiki 页面

#### 摘要页 (`wiki/summaries/`)

```bash
Write wiki/summaries/{doc_title}.md
```

内容要点：来源信息、核心观点、关键论据、方法论、局限性。必须包含 `> 来源: sources/{doc_id}/` 引用。

#### 概念页 (`wiki/concepts/`)

对每个重要概念：

```bash
# 新建
Write wiki/concepts/{concept-name}.md

# 或更新已有
Edit wiki/concepts/{concept-name}.md
```

如果概念页已存在，用 Edit 追加新来源的信息。每个概念页标注哪些源文档提到了它。

#### 实体页 (`wiki/entities/`)

对重要人物、产品、组织，同样新建或更新。使用 `[[双括号链接]]` 建立页面间的交叉引用。

### 阶段 7: 更新 index.md

用 Edit 在 `wiki/index.md` 中：
- 在对应分类下添加新页面的链接和一行摘要
- 如果已有页面被更新了，更新其摘要行

### 阶段 8: 追加 log.md

用 Edit 在 `wiki/log.md` 末尾追加：

```markdown
## [YYYY-MM-DD] ingest | {文档标题}
- 来源: sources/{doc_id}/
- 新增摘要: [summaries/{title}.md](summaries/{title}.md)
- 新增概念: xxx, yyy
- 更新页面: concepts/zzz.md（补充新来源引用）
- 关键收获: <一句话>
```

### 阶段 9: 提交变更

```bash
git add -A
git commit -m "ingest: {doc_id} — {文档标题}

- 新增摘要: summaries/{title}.md
- 更新概念: concepts/xxx.md
- 更新 index.md 和 log.md"
```

分支 `ingest/{doc_id}` 现在包含了所有变更，待用户在审核界面审查。

## Re-ingest（源文档更新后）

当源文档有新版本时，在 `reingest/{doc_id}` 分支上：

1. 读新版本源文件
2. 读现有相关 wiki 页面
3. 对比分析：新内容是否与旧断言矛盾？
4. 更新摘要页、受影响的概念/实体页
5. 在 log.md 记录变更
6. 提交：`git commit -m "reingest: {doc_id} v2 — 摘要更新"`

## 示例

用户: "ingest 001__detr-paper"

Agent 执行:
```
1. ls sources/001__detr-paper/
   → source.pdf
2. git checkout -b ingest/001__detr-paper
3. pdf-oxide 提取文本 → 读取全文
4. rg -i "object.detection|transformer|DETR" wiki/
5. ls -R wiki/summaries/ wiki/concepts/
6. Write wiki/summaries/detr-paper.md
7. Write wiki/concepts/bipartite-matching.md (新建)
8. Edit wiki/concepts/transformer.md (追加 DETR 相关信息)
9. Edit wiki/index.md (更新条目)
10. Edit wiki/log.md (追加日志)
11. git add -A && git commit -m "ingest: 001__detr-paper — DETR 论文"
```
