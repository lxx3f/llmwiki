---
name: lint
description: 对 wiki 进行健康检查——矛盾检测、孤立页面、过时内容、缺失交叉引用
---

# Lint 技能

触发条件：用户说 "lint"、"检查 wiki"、"健康检查"、"审查知识库" 等。

## 核心理念

lint 分两层：

1. **确定性检查**（由 `lint` 工具完成）：stats / orphans / outdated / unindexed / contradiction_ctx
2. **语义判断**（由 LLM 完成）：基于 contradiction_ctx 上下文判断 snippets 是否真矛盾

Agent 不再手写 ripgrep + git log 脚本——直接调 `lint` 工具拿结构化数据。

## 工作流

### 1. 调用 lint 工具

```
lint action="scan" kb_slug="main"
```

返回结构：
- `stats` — 页面/源文档统计
- `orphans` — 无入站引用的孤立页面
- `outdated` — 源文件比最后 ingest commit 新的文档
- `unindexed` — 存在但 index.md 没列出的内容页
- `contradiction_ctx` — 核心概念在多页面的提及片段（你来判断）

### 2. LLM 判断矛盾

读 `contradiction_ctx` 里的 snippets，判断：

- 不同页面是否对同一概念做了**矛盾的事实声明**
- 重点关注：统计数据、日期、因果关系、技术细节
- 多数情况是互补而非矛盾——谨慎报告

### 3. 写健康报告到 synthesis/

写到 `<kb>/wiki/synthesis/health-report-<YYYY-MM-DD>.md`：

```markdown
# Wiki 健康报告 — YYYY-MM-DD

> 检查范围: {kb} | 页面: N | 源文档: M

## 🔴 矛盾（事实冲突）

- ❌ concepts/A.md vs concepts/B.md 关于 "X":
  - A.md 声称: "..."
  - B.md 声称: "..."

## 🟡 过时（建议复查）

- 003__xxx — 源已更新但 wiki 未跟进

## 🔗 孤立（需要链接）

- concepts/yyy.md — 无任何 wiki 页面引用它

## 整体状态

- 知识覆盖: 🟢 / 🟡 / 🔴
- 关键风险: 0 个事实矛盾，2 个过时源

## 建议下一步

1. ...
```

### 4. 提交

```bash
git add -A
git commit -m "lint: <kb> 健康检查 <YYYY-MM-DD>"
```

Agent 会自动 checkout master。

## 原则

- 不把 lint 工具的原始 JSON 输出塞进 wiki——读它，理解它，写人类可读的报告
- 矛盾判断要谨慎——不同时期、不同角度的描述不算矛盾
- 报告本身是 wiki 页面——写得好读、给可执行建议