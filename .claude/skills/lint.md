---
name: lint
description: 对 wiki 进行健康检查——矛盾检测、孤立页面、过时内容、缺失交叉引用
---

# Lint 技能

触发条件：用户说 "lint"、"检查 wiki"、"健康检查"、"审查知识库" 等。

## 核心理念

wiki 随着增长会积累问题：新旧知识矛盾、孤立页面、过时论断、缺失交叉引用。Agent 是唯一能系统性做这种维护工作的实体。

## 工作流程

### 阶段 1: 获取全局视图

```bash
# 目录结构
ls -R wiki/

# 索引和日志
cat wiki/index.md
cat wiki/log.md

# 页面总数
find wiki/ -name "*.md" | wc -l
```

### 阶段 2: 矛盾检测

检查不同页面之间的事实性声明是否一致。

**方法**:
1. 从 index.md 识别核心概念和实体
2. 用 ripgrep 对每个核心主题搜索所有提及它的页面：
   ```bash
   rg -i "<核心主题>" wiki/
   ```
3. 读取相关页面，比较声明
4. 重点关注：统计数据、日期、因果关系声明、技术细节

**输出格式**:
```
⚠️ 矛盾: concepts/A.md 声称 "X 是 Y 的原因"
         但 summaries/B-paper.md 的结论是 "X 与 Y 无关"
   → 建议: 进一步查证或标注不确定性
```

### 阶段 3: 孤立页面检测

识别没有被任何其他页面引用的页面。

**方法**:
```bash
# 获取所有 wiki 页面列表
find wiki/ -name "*.md" -not -name "index.md" -not -name "log.md"

# 对每个页面，检查是否被其他页面引用
for page in wiki/**/*.md; do
  pagename=$(basename "$page" .md)
  refs=$(rg -l "$pagename" wiki/ --glob '!index.md' --glob '!log.md' | grep -v "$page" | wc -l)
  if [ "$refs" -eq 0 ]; then
    echo "孤立: $page"
  fi
done
```

**输出格式**:
```
🔗 孤立页面: concepts/obscure-topic.md — 无页面链接到它
   → 建议: 添加相关页面的交叉引用，或考虑合并
```

### 阶段 4: 过时内容检测

**方法**:
1. 查 log.md 看最早 ingest 的时间和最新源加入的时间
2. 识别有更新的源（源 commit 晚于最后 ingest commit）：
   ```bash
   for dir in sources/*/; do
     doc_id=$(basename "$dir")
     last_ingest=$(git log --oneline master --grep="ingest: $doc_id" --format="%H" -1)
     last_source=$(git log --oneline master --format="%H" -1 -- "$dir")
     if [ -n "$last_ingest" ] && [ "$last_source" != "$last_ingest" ]; then
       echo "需要 re-ingest: $doc_id"
     fi
   done
   ```
3. 检查早期页面引用的源是否已被新源覆盖

**输出格式**:
```
🕐 可能过时: synthesis/object-detection.md 基于 2024-03 的源，
          但 2026-06 新增了两篇相关论文且未 re-ingest
   → 建议: 重新审定
```

### 阶段 5: 缺失交叉引用

**方法**: 检查语义相关的页面是否互相链接了。
```bash
# 搜索可能相关但未互链的页面
rg -i "<主题A>" wiki/ --files-with-matches
rg -i "<主题B>" wiki/ --files-with-matches
# 检查两个结果集中的页面是否互含对方链接
```

**输出格式**:
```
🔀 缺少交叉引用: concepts/A.md 和 concepts/B.md 讨论紧密相关主题但未互链
```

### 阶段 6: 综合报告

输出总结性健康报告：

```markdown
# Wiki 健康报告 — [YYYY-MM-DD]

## 总览
- Wiki 页面总数: N
- 源文档总数: M
- 待 re-ingest: K
- 发现问题: X

## 按严重程度

### 🔴 矛盾（需立即关注）
...

### 🟡 过时（建议复查）
...

### 🔗 孤立（需要链接）
...

### 🔀 交叉引用缺失
...

### 📝 建议创建
...

## 建议下一步
1. ...
2. ...
```

## 示例

用户: "/lint"

Agent 执行:
```
1. cat wiki/index.md → 了解全局
2. rg 抽查关键页面
3. 运行孤立页面脚本
4. 运行 re-ingest 检测
5. 综合生成健康报告
```
