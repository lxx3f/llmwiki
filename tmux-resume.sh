#!/bin/bash

SESSION="llmwiki"
ROOT=~/repositories/llmwiki

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "会话 $SESSION 已存在，正在 attach..."
  tmux attach -t "$SESSION"
  exit 0
fi

echo "创建 tmux 会话: $SESSION"

# ── 布局 (base-index=1) ────────────────────────────────
# ┌────────────────┬────────────────┐
# │  pane 1: API   │  pane 3: MCP   │  ← 上 ~75%
# ├────────────────┴────────────────┤
# │  pane 2: 备用                    │  ← 下 ~25%
# └─────────────────────────────────┘
# 分割顺序: 初始(.1) → 垂直分下(.2) → 在上(.1)水平分右(.3)

# 1. 创建会话
tmux new-session -d -s "$SESSION" -n "$SESSION" -c "$ROOT"

# 2. 垂直分割
tmux split-window -v -p 50 -t "$SESSION:1" -c "$ROOT/api"

# 3. 水平分割 
tmux split-window -h -t "$SESSION:1.1" -c "$ROOT/mcp"

# ── 启动服务 ─────────────────────────────────────────
# 上左 .1: API 服务
tmux send-keys -t "$SESSION:1.1" \
  "python -m uvicorn main:app --reload --port 8001" Enter

# 上右 .3: MCP 服务
tmux send-keys -t "$SESSION:1.3" \
  "python -m uvicorn server:app --reload --port 8080" Enter

# 选中上左后 attach
tmux select-pane -t "$SESSION:1.1"
tmux attach -t "$SESSION"
