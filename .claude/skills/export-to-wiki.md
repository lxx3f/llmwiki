---
name: export-to-wiki
description: 从当前 Claude 对话中提取关键知识点，导出到 LLM Wiki
---

# 对话导出技能

触发条件：用户说"导出到 wiki"、"export to wiki"、"保存到知识库"等。

## 工作流程

### 1. 搜索现有 wiki

首先调用 MCP `search` 工具浏览当前 wiki 的结构：

```
search(knowledge_base="<你的知识库>", mode="list")
```

了解现有 wiki 页面和标签，避免重复创建。

### 2. 从对话中提取知识点

回顾当前对话历史，识别以下类型的可沉淀内容：

- **决策**：做出的技术选型、架构决策、为什么选 A 不选 B
- **知识点**：新学的概念、API 用法、配置方法
- **解决方案**：代码片段、配置、操作步骤
- **陷阱/经验**：遇到的问题和解决过程
- **创意/想法**：值得记录的思路

### 3. 创建或更新 wiki 页面

对每条知识点，使用 `write` 工具：

```
write(command="create", path="/wiki/concepts/", title="<页面标题>.md",
      content="<markdown 内容>", tags=["<相关标签>"])
```

**页面格式要求**：
- 标题清晰概括内容
- 正文包含：背景、要点、示例（代码或配置）
- 如有原始来源，用脚注标注 `[^1]: <来源描述>`
- 最小化：每个页面聚焦一个明确的知识点

### 4. 打标签

使用合适的标签分类，例如：
- `编程/Python`、`编程/Rust`
- `部署/Docker`
- `配置`
- `想法`
- `经验`

（标签通过 MCP tags 参数传递，或使用 `/tags` 页面管理）

### 5. 更新 overview

如果有重要新增，更新 `/wiki/overview.md`：
```
write(command="str_replace", path="/wiki/overview.md",
      old_text="<要替换的部分>", new_text="<更新后的内容>")
```

### 6. 追加 log

```
write(command="append", path="/wiki/log.md",
      content="## [YYYY-MM-DD] export | 对话导出\n- 新增页面: [Page](page.md)\n- 关键收获: <一句话>")
```

## 示例

用户：把今天讨论的 PostgreSQL 性能优化方案导出到 wiki

Claude 执行：
1. search 查看现有 wiki 结构
2. 识别知识点：PostgreSQL 索引策略、查询优化、连接池配置
3. write 创建 `/wiki/concepts/postgres-query-optimization.md`
4. write 创建 `/wiki/concepts/postgres-connection-pooling.md`
5. write 更新 `/wiki/overview.md` 的关键发现
6. write append `/wiki/log.md` 记录导出
