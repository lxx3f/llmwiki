---
name: query
description: 对 wiki 进行智能查询——优先读取已编译的 wiki 页面，不足时回退到 RAG 搜索原始文档
---

# Query 技能

触发条件：用户向 wiki 提问时自动使用（如 "wiki 里关于 X 有什么?"、"对比 Y 和 Z"）。

## 核心理念

Karpathy LLM Wiki 与传统 RAG 的区别：**查询应对已编译的 wiki 页面进行，而非每次对 raw chunks 重新综合**。知识已在 ingest 时编译好了。只有当 wiki 页面覆盖不足时，才回退到 RAG 搜索原始文档。

## 工作流程

### 步骤 1: 先读 index.md

```
read(knowledge_base="<kb>", path="/wiki/index.md")
```

index.md 是 wiki 的内容地图。先读它了解哪些页面可能与问题相关。

### 步骤 2: 搜索 wiki 页面

```
search(knowledge_base="<kb>", mode="search", scope="wiki", query="<关键词>")
```

用 `scope="wiki"` 限定只搜索已编译的 wiki 页面。

### 步骤 3: 读取最相关的 wiki 页面

根据 index 和搜索结果，读取 2-5 个最相关的 wiki 页面：
```
read(knowledge_base="<kb>", path="/wiki/concepts/xxx.md")
read(knowledge_base="<kb>", path="/wiki/synthesis/xxx.md")
```

### 步骤 4: 综合回答

基于读到的 wiki 页面内容综合回答。引用来源用 `[^1]: /wiki/...` 格式。

### 步骤 5: 回退处理（仅在 wiki 覆盖不足时）

如果 wiki 页面不能充分回答问题（例如这是一个新领域，还没有相关 wiki 页面）：

1. 使用 `search(scope="sources")` 搜索原始文档
2. 使用 `ask` 工具触发 RAG 检索 raw chunks
3. 综合回答，并在回答末尾**标记这是从原始文档综合的、尚未编译为 wiki**

### 步骤 6: 归档有价值的回答

如果这个回答揭示了一个值得保存的洞察：
- 告诉用户 "这个发现值得保存到 wiki"
- 建议使用 `/export-to-wiki` 或 ingest 流程

## 关键原则

- **Wiki 优先**：总是先查 wiki 页面，它们是已编译的知识
- **标记来源层级**：让用户知道答案来自 wiki 页面还是 raw RAG
- **引而不发**：好答案应进入 wiki——提醒但不强制

## 示例

用户: "wiki 里有关于注意力机制的什么内容？"

Claude 执行:
1. `read(path="/wiki/index.md")` → 发现 concepts/attention.md
2. `search(scope="wiki", query="attention")` → 确认相关页面
3. `read(path="/wiki/concepts/attention.md")` → 读取完整内容
4. `read(path="/wiki/concepts/transformer.md")` → 读取关联概念
5. 综合回答，引用具体 wiki 页面
