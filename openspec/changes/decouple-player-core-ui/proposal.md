## Why

`autoplaylist/player.py` 的 `play_playlist()` 把播放状态/调度、TUI 渲染、键盘输入四件事拧成 1700 行的一团麻花。任何与"播放生命周期"相关的演进（例如后台常驻、attach/detach、外部命令控制、状态导出到状态栏）都被这个耦合卡死。本次变更仅做一件事：把**播放核心**从**终端界面**里剥出来，为后续演进铺路，但**不改变任何现有用户可见行为**。

## What Changes

- 引入 `PlayerCore`：持有播放状态（当前曲目、播放/暂停、play_mode、view_start、cursor、歌词状态、mpv 句柄等）与调度循环（曲目推进、mpv IPC 调用、歌词同步），对外暴露命令方法（`next / prev / toggle_pause / seek / set_mode / ...`）和事件订阅机制。
- 将 TUI 重构为 `PlayerCore` 的**订阅者**：按键输入翻译成 core 命令；渲染只读 core 的状态快照和事件，不再直接修改状态。
- `play_playlist()` 的职责缩减为：构造 `PlayerCore` + 挂载 TUI 视图 + 运行事件循环。
- **行为零变化**：所有按键、视觉输出、tab 切换、歌词面板、seek、cache ⚡ 标记、mood 动画等保持与当前一致。
- **非目标**：不做 daemon/fork、不加 IPC 子命令、不改 mpv 启动方式、不做任何 UI 视觉调整；拆分过程中发现的既有 bug 不顺手修，单独开 change。

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
- `playlist-player`：**内部结构性重构**。对外 requirements 不变，但需在 spec 中显式记录"播放核心与 UI 解耦"这一架构约束，为后续 daemon 化等变更提供 spec 层面的抓手。

## Impact

- **代码**：主要影响 `autoplaylist/player.py`。`_commands.py` / `cli.py` 中对 `play_playlist` 的调用点保持签名兼容。
- **测试**：`tests/` 下涉及 player 的用例需继续通过；解耦后可为 `PlayerCore` 增补纯状态机单测（建议，非强制）。
- **API / 依赖**：无新增依赖，无对外 API 变化。
- **风险**：1700 行函数拆分容易引入回归（尤其光标定位、歌词面板切换、tab 切换时的状态重置）。需在 `design.md` 中明确拆分边界和回归验证策略。
