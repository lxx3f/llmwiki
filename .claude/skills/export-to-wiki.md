---
name: export-to-wiki
description: 从当前 Claude 对话中提取关键知识点，导出到 LLM Wiki
---

# Export to Wiki 技能

触发条件：用户说 "导出到 wiki"、"export to wiki"、"保存到知识库"、"这个记下来" 等。

## 核心理念

Karpathy 的核心洞察之一：**好答案应该归档回 wiki**。一次有洞见的分析、一个发现的关联、一个澄清的概念——这些不应该消失在聊天历史中。Export 是比 ingest 更轻量的工作流——它不是处理完整源文档，而是将对话中产出的知识点沉淀到 wiki。

## 工作流程

### 步骤 1: 理解现有 wiki

```
search(knowledge_base="<kb>", mode="list", scope="wiki")
read(knowledge_base="<kb>", path="/wiki/index.md")
```

了解当前 wiki 结构，确保不重复创建已有页面。

### 步骤 2: 提取知识点

回顾当前对话，识别以下类型的可沉淀内容：

- **决策/选择**: 为什么选 A 不选 B，trade-off 分析
- **知识点**: 新学的概念、API 用法、配置方法
- **解决方案**: 代码片段、修复步骤、调试方法
- **陷阱/教训**: 遇到的问题和解决过程
- **关联/洞察**: 把两个不相关的事联系起来的新视角

用 `ask` 工具辅助验证（如果需要从知识库中查找相关信息做交叉引用）。

### 步骤 3: 分类并写入

根据知识点类型选择对应路径：

| 类型 | 路径 | 示例 |
|------|------|------|
| 概念解释 | `/wiki/concepts/` | `postgres-query-planning.md` |
| 技术决策 | `/wiki/concepts/` 或 `/wiki/synthesis/` | `why-asyncpg-over-sqlalchemy.md` |
| 解决方案 | `/wiki/concepts/` | `fix-ollama-connection-timeout.md` |
| 对比分析 | `/wiki/synthesis/` | `pgvector-vs-pgroonga.md` |
| 项目经验 | `/wiki/synthesis/` | `lessons-from-single-user-migration.md` |

```
write(command="create", path="/wiki/<category>/",
      title="<descriptive-name>.md",
      content="<markdown>", tags=["<相关标签>"])
```

**页面格式要求**:
- 标题清晰概括内容
- 必须包含来源标注: `[^context]: <对话上下文>`
- 正文结构: 背景 → 要点 → 细节/示例 → 关联页面
- 添加 `[[双括号链接]]` 指向相关 wiki 页面
- 每个页面聚焦一个明确的知识点（不要多个不相关的知识点混在一个页面）

### 步骤 4: 更新已有页面

如果新知识点是已有页面的补充或更新，用 `str_replace`：
```
write(command="str_replace", path="/wiki/concepts/existing.md",
      old_text="<要替换的部分>", new_text="<更新的内容>")
```

### 步骤 5: 更新 index.md

在 index.md 对应分类下添加新页面：
```
write(command="str_replace", path="/wiki/index.md",
      old_text="## Concepts (概念)\n", 
      new_text="## Concepts (概念)\n- [新页面](wiki/concepts/new-page.md) — 一句话描述\n")
```

### 步骤 6: 追加 log.md

```
write(command="append", path="/wiki/log.md",
      content="## [YYYY-MM-DD] export | 对话导出\n- 新增页面: [page](path)\n- 更新页面: [page](path)\n- 关键收获: <一句话>")
```

### 步骤 7: 报告

总结导出内容：新增 N 个页面，更新 M 个页面，打标签 T。

## 标签建议

使用平面标签对页面分类（可选但推荐）:

- `编程/Python`, `编程/Rust`, `编程/数据库`
- `部署/Docker`, `部署/CI-CD`
- `AI/LLM`, `AI/Embedding`
- `架构`, `性能`, `安全`
- `经验`, `想法`, `调试`

## 示例

用户: "把今天讨论的为什么 ILIKE 降级在 PGroonga 不可用时能工作导出到 wiki"

Claude 执行:
1. `search(scope="wiki")` → 了解现有结构
2. `read(path="/wiki/index.md")` → 确认无重复页面
3. 提取知识点: pgvector 镜像不含 PGroonga → ILIKE 作为最后降级方案的原因和实现
4. `write(create, "/wiki/concepts/search-fallback-strategy.md")` → 创建页面
5. `write(str_replace, "/wiki/index.md")` → 更新索引
6. `write(append, "/wiki/log.md")` → 记录导出
7. 报告: 新增 1 个页面，标签 `搜索`, `数据库`
