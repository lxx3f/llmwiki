# tmux 常用命令参考

## 基本概念

tmux 采用三层结构：

| 层级              | 说明                       |
| --------------- | ------------------------ |
| **Session（会话）** | 最顶层，包含一组窗口               |
| **Window（窗口）**  | 相当于一个标签页，包含一组窗格          |
| **Pane（窗格）**    | 终端的分割区域，每个窗格是一个独立的 shell |

---

	## 一、Session（会话）管理

### 命令行操作

| 命令                                   | 说明                      |
| ------------------------------------ | ----------------------- |
| `tmux`                               | 新建无名会话                  |
| `tmux new -s <name>`                 | 新建名为 `<name>` 的会话       |
| `tmux new -s <name> -d`              | 后台创建会话（不自动进入）           |
| `tmux ls` / `tmux list-sessions`     | 列出所有会话                  |
| `tmux attach -t <name>`              | attach 到名为 `<name>` 的会话 |
| `tmux attach`                        | attach 到最近使用的会话         |
| `tmux kill-session -t <name>`        | 删除指定会话                  |
| `tmux kill-server`                   | 杀掉 tmux 服务器（删除所有会话）     |
| `tmux rename-session -t <old> <new>` | 重命名会话                   |

### 快捷键（默认前缀 `Ctrl+b`）

| 快捷键 | 说明 |
|--------|------|
| `Prefix s` | 列出所有会话，可切换 |
| `Prefix d` | detach（分离）当前会话 |
| `Prefix $` | 重命名当前会话 |
| `Prefix (` | 切换到上一个会话 |
| `Prefix )` | 切换到下一个会话 |

---

## 二、Window（窗口）管理

### 快捷键

| 快捷键 | 说明 |
|--------|------|
| `Prefix c` | 创建新窗口 |
| `Prefix ,` | 重命名当前窗口 |
| `Prefix w` | 列出所有窗口，可切换 |
| `Prefix n` | 切换到下一个窗口 |
| `Prefix p` | 切换到上一个窗口 |
| `Prefix 0-9` | 切换到指定编号的窗口 |
| `Prefix &` | 关闭当前窗口（需确认） |
| `Prefix f` | 按名称查找窗口 |
| `Prefix .` | 修改当前窗口的索引编号 |
| `Prefix '` | 切换到指定名称的窗口 |

### 命令行

| 命令 | 说明 |
|------|------|
| `tmux new-window -t <session> -n <name>` | 在指定会话中创建命名窗口 |
| `tmux kill-window -t <window>` | 删除指定窗口 |

---

## 三、Pane（窗格）管理

### 分割窗格

| 快捷键 | 说明 |
|--------|------|
| `Prefix %` | 垂直分割（左右分屏） |
| `Prefix "` | 水平分割（上下分屏） |

### 导航（切换焦点）

| 快捷键 | 说明 |
|--------|------|
| `Prefix ↑/↓/←/→` | 按方向切换窗格 |
| `Prefix o` | 循环切换到下一个窗格 |
| `Prefix ;` | 切回上一个活跃窗格 |
| `Prefix q` + 数字 | 按编号跳转到指定窗格 |

### 调整大小

| 快捷键 | 说明 |
|--------|------|
| `Prefix Ctrl+↑/↓/←/→` | 按方向调整窗格大小（每次 1 行/列） |
| `Prefix Alt+↑/↓/←/→` | 按方向调整窗格大小（每次 5 行/列） |

### 窗格布局

| 快捷键 | 说明 |
|--------|------|
| `Prefix Space` | 循环切换预设布局 |
| `Prefix Alt+1` | 水平等分布局 (even-horizontal) |
| `Prefix Alt+2` | 垂直等分布局 (even-vertical) |
| `Prefix Alt+3` | 主窗格在左，其余垂直排列 (main-vertical) |
| `Prefix Alt+4` | 主窗格在上，其余水平排列 (main-horizontal) |
| `Prefix Alt+5` | 平铺布局 (tiled) |

### 窗格操作

| 快捷键 | 说明 |
|--------|------|
| `Prefix x` | 关闭当前窗格（需确认） |
| `Prefix z` | 最大化/还原当前窗格（toggle zoom） |
| `Prefix !` | 将当前窗格拆出为新窗口 |
| `Prefix {` | 将当前窗格与上一个窗格交换位置 |
| `Prefix }` | 将当前窗格与下一个窗格交换位置 |
| `Prefix t` | 在当前窗格显示时钟 |
| `Prefix Ctrl+o` | 顺时针旋转窗格 |

---

## 四、复制模式（Copy Mode）与滚动

| 快捷键 | 说明 |
|--------|------|
| `Prefix [` | 进入复制模式（可上下滚动查看历史输出） |

### 复制模式下的操作（vi 风格，默认）

| 按键 | 说明 |
|------|------|
| `↑/↓/←/→` 或 `h/j/k/l` | 移动光标 |
| `Ctrl+u` | 向上翻半页 |
| `Ctrl+d` | 向下翻半页 |
| `Ctrl+b` | 向上翻页 (Page Up) |
| `Ctrl+f` | 向下翻页 (Page Down) |
| `g` | 跳到缓冲区开头 |
| `G` | 跳到缓冲区结尾 |
| `Space` | 开始选中文本 |
| `Enter` | 复制选中的文本并退出复制模式 |
| `Esc` / `q` | 退出复制模式 |
| `v` | 切换块选 / 行选模式 |
| `/` | 向下搜索 |
| `?` | 向上搜索 |
| `n` | 跳到下一个搜索结果 |
| `N` | 跳到上一个搜索结果 |

> **提示**：在 tmux 配置中设置 `set -g mouse on` 后，可以直接用鼠标滚轮滚动和选中复制。

---

## 五、其他常用操作

| 快捷键 | 说明 |
|--------|------|
| `Prefix ?` | 显示所有快捷键列表 |
| `Prefix :` | 进入命令模式（可输入 tmux 命令） |
| `Prefix r` | 重新加载 tmux 配置文件 |
| `Prefix i` | 显示当前窗格信息 |

### 常用命令模式命令

在 `Prefix :` 后输入：

| 命令 | 说明 |
|------|------|
| `source-file ~/.tmux.conf` | 重载配置文件 |
| `set -g mouse on` | 启用鼠标支持 |
| `set -g mouse off` | 禁用鼠标支持 |
| `set -g status off` | 隐藏状态栏 |
| `set -g status on` | 显示状态栏 |
| `setw -g mode-keys vi` | 复制模式使用 vi 键位 |
| `display-panes` | 显示每个窗格的编号 |
| `clock-mode` | 时钟模式 |

---

## 六、常用配置示例（~/.tmux.conf）

```bash
# 将前缀键从 Ctrl+b 改为 Ctrl+a（更顺手）
# set -g prefix C-a
# unbind C-b
# bind C-a send-prefix

# 启用鼠标（滚动、选窗格、调大小）
set -g mouse on

# vi 风格复制模式
setw -g mode-keys vi

# 从 1 开始编号窗口（而非 0）
set -g base-index 1
setw -g pane-base-index 1

# 更直观的窗格分割快捷键
bind | split-window -h   # Prefix | 垂直分割
bind - split-window -v   # Prefix - 水平分割

# Vim 风格窗格导航
bind h select-pane -L
bind j select-pane -D
bind k select-pane -U
bind l select-pane -R

# 加快按键响应（默认的 escape-time 太长）
set -sg escape-time 0
```

---

## 七、常见场景速查

```bash
# 创建新会话
tmux new -s dev

# 列出会话
tmux ls

# 重新 attach
tmux attach -t dev

# 在 dev 会话中创建新窗口
tmux new-window -t dev -n server

# 从外部发送命令到会话
tmux send-keys -t dev:1 'ls -la' Enter

# 删除 dev 会话
tmux kill-session -t dev

# 同时推送到所有窗格（在 Prefix : 后输入）
setw synchronize-panes on    # 开启同步
setw synchronize-panes off   # 关闭同步
```

---

## 八、默认前缀说明

- 默认前缀键：**`Ctrl+b`**
- 用法：先按 `Ctrl+b`，松开后再按对应的快捷键
- 示例：`Ctrl+b` → `%`（垂直分割窗格）
