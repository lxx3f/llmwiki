---
name: wrap-up
description: 总结本次会话改动、检查并更新 README/CLAUDE.md/skills 文档
---

# Wrap-up 技能

触发条件：用户说 "/wrap-up"、"总结一下"、"整理文档"、"这阶段完了"、"更新 readme"、"更新文档" 等。

## 核心理念

每次会话结束后，把**有意义的改动**反映到项目文档里，让下次进入项目的人（或未来的你）能快速理解当前状态。

**约束**：
- **不替用户 commit** —— 写文档可以，但 git commit 是用户决定
- **先 review 再写** —— 把所有 propose 改动一次性展示，逐项批准后才落盘
- **默认包含所有改动**（已 commit + 未 commit），但让用户在第 1 步选基线
- **不强制改文档** —— 如果改动不值得写文档（如纯 typo 修复、debug 调试），用户可跳过

## 工作流

### 阶段 1: 探测状态 + 选基线

运行以下命令探测：

```bash
# 当前分支
git branch --show-current

# 工作区状态（未 commit）
git status --porcelain

# 分支 vs master 的 diff（已 commit 但未 merge）
git diff master...HEAD --stat

# 工作区 vs master（全量）
git diff master --stat
```

把结果展示成这样的表格：

```
┌──────────────────────────────────────────────────────────────────┐
│ 探测结果                                                           │
├──────────────────────────────────────────────────────────────────┤
│ 当前分支: feature-x (master 之前有 5 个 commit)                     │
│ 工作区: 2 modified, 1 untracked                                   │
│ 分支 vs master: 5 commits, +340/-120                              │
│ 工作区 vs master: 5 commits + 2 modified + 1 untracked, +360/-125 │
└──────────────────────────────────────────────────────────────────┘

这次 wrap-up 想总结哪些改动？
[1] 只看工作区未 commit 的（适合：边改边 wrap-up，最后一次提交）
[2] 看分支上未 merge 到 master 的（适合：feature 分支开发完，准备提 PR）
[3] 看全部 working tree vs master（推荐，覆盖所有）
[4] 自定义基线（指定 commit/tag/分支）
```

**等待用户回答**。如果用户说"默认"或"用 [3]"，选 [3]。

### 阶段 2: 收集改动列表

根据用户选择的基线，列出具体改动的文件：

```bash
# 例：选项 3（master vs working tree）
git diff master --name-status
# 输出:
# M       api/main.py
# A       agent/tools/lint.py
# ??      agent/.state.json  (新增未跟踪)
```

**分类**：
- **code**: `api/` `agent/` `mcp/` `tests/` 下的文件
- **docs**: `README.md` `CLAUDE.md` `.claude/skills/*.md`
- **config**: `.env.example` `requirements.txt` `settings.json`
- **other**: 其他（如脚本、配置文件）

**对 .state.json / .cache/ 这类运行时产物 → 排除**，不写文档。

### 阶段 3: 检查文档同步情况

对每个**有意义的 code 改动**（不是 typo / debug / 重命名），反查它是否在文档中被提到：

```bash
# 找出文档中可能引用了某个文件/概念的所有段落
rg -n "manifest|extract_pdf|state.json" README.md .claude/skills/
rg -n "agent/tools/" README.md .claude/skills/
```

**关注点**：
- **README.md**: 系统组成图、Agent Tools 表、工作流步骤、文件结构示例
- **CLAUDE.md**: 架构关键概念、常见命令、API 路由结构、环境变量
- **.claude/skills/<skill>.md**: 工作流步骤、工具用法、决策表

**输出文档同步状态表**：

```
┌──────────────────┬──────────────────┬────────────────────┬────────────┐
│ code 改动         │ 受影响文档        │ 现状                │ 建议       │
├──────────────────┼──────────────────┼────────────────────┼────────────┤
│ 新增 lint.py     │ README.md        │ Agent Tools 表无 lint│ 加一行     │
│ 新增 /agent 面板  │ README.md        │ 系统组成图未提      │ 更新图     │
│ 新增 manifest 工具│ README.md .claude/skills/ingest.md │ 已涵盖（上周改过）│ 跳过 │
│ run.py 改 state  │ README.md        │ 工作流未提 state    │ 加一行     │
└──────────────────┴──────────────────┴────────────────────┴────────────┘
```

### 阶段 4: 生成具体 edit

对每条"建议"为 **Y** 的项：

1. 用 `Read` 读对应文档
2. 定位需要修改的段落（用 grep 找锚点）
3. 用 `Edit` 替换（在老文本旁加新内容 / 改一行 / 加新段落）

**生成每条建议的精确 edit**，不执行，先汇总。

### 阶段 5: 展示所有 propose 改动 + 等批准

把所有 propose 的 edit 一次性展示成：

```markdown
## 提议的文档改动

### 改动 1: README.md — Agent Tools 表加 lint

文件: README.md
锚点: "| `extract_pdf` | ..." 这一行之后

OLD:
| `extract_pdf` | `python -c "from pdf_oxide..."` | ... |

NEW:
| `extract_pdf` | `python -c "from pdf_oxide..."` | ... |
| `lint`        | ripgrep + git log | wiki 健康检查（stats/orphans/outdated/unindexed/contradiction_ctx） |

---

### 改动 2: README.md — 系统组成图加 /agent 面板

...

---

请逐项回复：
- "1 ✓ 2 ✗ 3 ✓" — 应用 1 和 3，跳过 2
- "全部应用" — 所有都用
- "全部跳过" — 不改文档，只生成总结
- "调整 X" — 对某项提出修改意见
```

**等用户回答**才能继续。不要假设。

### 阶段 6: 应用 + 总结报告

对每条批准的改动：用 `Edit` 写文件。

写完后给一份总结报告：

```markdown
## 本次 wrap-up 总结

### 项目改动概览
- 新增: agent/tools/lint.py, api/templates/agent.html
- 修改: api/main.py (+60 行), api/templates/base.html (+1 nav)
- 删除: (无)

### 文档更新
- README.md: 应用了 3 条建议
- CLAUDE.md: 无需更新（架构未变）
- .claude/skills/ingest.md: 上周已同步

### 下一步建议
- git commit 这些文档改动（我不会替你 commit）
- 重新 review 一下生成的措辞
```

### 阶段 7: 打 wrap-up tag（可选，建议）

如果你批准了文档改动，建议打个轻量 tag 标记这次基线，下次 wrap-up 默认从这里 diff：

```bash
git tag .wrap-up-$(date +%Y%m%d-%H%M)
git tag -l '.wrap-up-*' | sort | tail -5  # 列出最近的 tag
```

**询问用户**："要给这次打 wrap-up tag 吗？" 默认不打（避免污染 tag 列表）。

## 文档同步检查清单

跑完 wrap-up 后，确认：

- [ ] 新增的文件/工具/路由 都在文档里有提及
- [ ] 修改的命令、参数、行为 文档已同步
- [ ] 删除的功能 不再出现在文档里（或者标注 deprecated）
- [ ] 数字/统计（如"8 个工具"、"5 项检查"） 和代码一致
- [ ] 文件路径示例（如 `main/wiki/...`） 和实际一致
- [ ] 环境变量、配置项 和 `.env.example` 一致

## 边界情况

### 改动很小 / 都是 typo / debug

如果阶段 3 的表格里**没有"建议=Y"** 的行：

> 本次改动不值得更新文档（都是 typo / debug / 重命名 / 临时调试代码）。继续工作即可，无需更新 README/CLAUDE.md。

直接退出，不强写文档。

### 没有任何改动

如果 `git diff master --stat` 完全为空：

> 工作区干净且与 master 无差异。可能忘了 commit？或者这次会话没改代码？
> - 输入"总结这次对话"我可以基于对话内容生成
> - 输入"取消"退出

### 改动太大（> 30 个文件）

分批处理：

> 改动太多（45 文件），建议分批 wrap-up：
> - 批次 1: api/ 改动 (12 文件)
> - 批次 2: agent/ 改动 (8 文件)
> - 批次 3: docs/config (5 文件)
>
> 要全部一次性处理吗？还是先批次 1？

## 工具使用

| 操作 | 工具 |
|------|------|
| 探测 git 状态 | `Bash`（git status/diff/log） |
| 反查文档引用 | `Bash`（rg） 或 `Grep` |
| 读文档原文 | `Read` |
| 写文档改动 | `Edit`（精确替换，不用 Write 整文件重写） |
| 展示 propose 改动 | 终端输出 markdown 表格 |

## 反模式（不要做）

- ❌ 替用户 commit —— commit 是用户决定
- ❌ 跳过阶段 5 直接写文件 —— 必须先 review
- ❌ 改文档时用 Write 整文件重写 —— 用 Edit 精确替换更安全
- ❌ 把 lint 工具的原始 JSON 输出、未格式化的 git log 塞进文档 —— 文档是给人读的
- ❌ 给运行时产物（`.state.json`、`.cache/`、`.obsidian/`）写文档
- ❌ 在提议改动时只说"建议更新 README" —— 必须给出具体 edit
- ❌ 把所有改动都说"值得写文档" —— 要克制，多数小改动不需要