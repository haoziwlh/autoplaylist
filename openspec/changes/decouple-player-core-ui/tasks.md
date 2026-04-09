## 1. 准备与摸底

- [x] 1.1 通读 `autoplaylist/player.py`，列出 `play_playlist()` 闭包内所有可变状态变量。
- [x] 1.2 可变状态清单（作为第一步迁移的对照表）：

  **会话级（play_playlist 入口处一次性确定，tab 切换时重置）**
  - `active_idx: int` — 当前 playlist 下标（来自参数，tab 切换时 `(active_idx ± 1) % len(playlists)`）
  - `playlist_name: str` — 当前 playlist 名
  - `tracks: list[Track]` — 当前 playlist 曲目（list，删曲目/追加时原地改）
  - `prompt: str` — 当前 playlist 的 prompt
  - `n: int` — `len(tracks)` 的缓存
  - `vh: int` — viewport 高度 `min(_VIEW_H, n)`

  **播放游标与光标**
  - `current_idx: int` — 正在播放的曲目下标
  - `cursor_idx: int` — 用户光标选中的曲目下标
  - `view_start: list[int]` — `[0]` hack，viewport 首行对应的曲目下标
  - `paused: bool` — mpv 当前暂停态
  - `play_mode: str` — `"seq" | "repeat" | "shuffle"`

  **歌词状态（共享 dict）**
  - `_lyric: dict` — 字段 `line / off / idx / pos / mood / anim_t`
  - `_lrc_candidates: list[list[tuple[float,str]]]` — 每首曲目重置，歌词候选源
  - `_lrc_idx: list[int]` — `[0]` hack，当前使用的候选源下标
  - `_lrc_ready: list[bool]` — `[False]` hack，抓取完成标志
  - `_last_pos_ts: float` — mpv 位置轮询节流
  - `_last_step_ts: float` — marquee 步进节流
  - `_prev_lrc_line: Optional[str]` — 上一次显示的歌词行（用于检测 line 变化）

  **歌词面板**
  - `lyric_panel_on: bool` — 面板开关
  - `_panel_widths: Optional[tuple[int,int,int]]` — 面板宽度缓存

  **异步协作标志**
  - `_appending: list[bool]` — `[False]` hack，后台 append 运行中
  - `_switch_tab: list[int]` — `[0]` hack，tab 切换请求（-1/0/+1）

  **播放后端句柄**
  - `ytdlp_proc: Optional[subprocess.Popen]`
  - `mpv_proc: Optional[subprocess.Popen]`
  - `key_reader: _KeyReader` — 键盘读线程实例
  - `_orig_sigint` — 原 SIGINT handler 备份

  **输入缓冲（track 内循环局部）**
  - `num_buf: str` — 数字跳转缓冲
  - `num_ts: float` — 缓冲时间戳

- [x] 1.3 闭包写入点清单（`nonlocal` + `[0]=` 风格，`player.py` 行号）：
  - L950/952: `view_start[0] = ...`（`_scroll_to` 内）
  - L1126: `_appending[0] = False`（append 完成回调）
  - L1158: `nonlocal ytdlp_proc, mpv_proc`（`stop_current`）
  - L1190: `nonlocal current_idx, cursor_idx, paused`（`_jump_to`）
  - L1211: `_switch_tab[0] = 0`（主循环顶清零）
  - L1217: `view_start[0] = 0`（tab 切换重置）
  - L1225: `_appending[0] = False`（tab 切换重置）
  - L1283: `_lrc_ready[0] = True`（后台歌词抓取完成）
  - L1325/1594: `_switch_tab[0] = -1/+1`（`[` / `]` 键按下）
  - L1357: `nonlocal _last_pos_ts, _prev_lrc_line`（`_tick_lyric`）
  - L1481: `_appending[0] = True`（`+` 键触发 append）
  - L1525/1543: `_lrc_idx[0] = ...`（`y` 键切换歌词源）
  - L1551/1552: `_lrc_ready[0]=False; _lrc_idx[0]=0`（`Y` 键刷新歌词）
  - L1643/1652: `view_start[0] = new_vs`（LEFT/RIGHT 翻页）

- [x] 1.4 后台线程 / 异步源清单：
  - **`_KeyReader` 线程**（模块内独立类）：纯生产者，把按键塞自己的队列；不碰 core 状态。
  - **`_lrc_thread`（每曲一次）**：`_fetch_lyrics(artist,title)` → 写 `_lrc_candidates` / `_lrc_ready[0]`。**读** 无 core 状态。
  - **`_classify_mood_bg` 线程（每曲一次）**：写 `_lyric["mood"]`。无读。
  - **mpv 子进程**：主循环通过 `mpv_proc.poll()` 被动监听退出；退出后由主循环决定 auto-advance。**非独立线程**，但在状态机语义上等同于一个事件源。
  - **`_do_append` 线程（`+` 键触发，按需）**：写 `_appending[0]`；可能追加 `tracks`（经现有机制）。
  - **`_refresh_and_notify` 线程（`Y` 键触发，按需）**：写 `_lrc_candidates` / `_lrc_ready[0]`，调 `_status`（直接写 stdout——重构后要改为 post 事件）。
  - **位置/歌词 tick**：非独立线程，在主循环里按时间阈值调 `_tick_lyric`。

  **Core 迁移后的映射承诺**：上述每个异步源在新架构里只做一件事——`core.post(<Event>)`，绝不直写状态；`_status` 的直接 stdout 调用要重定向为 `core.post(StatusRequested(text))` → 由 UI 主循环渲染。

- [x] 1.5 调用点确认：仅 `autoplaylist/_commands.py:196` 一处调 `play_playlist(playlists, active_idx, debug=debug)`。签名保持 `(playlists, active_idx=0, debug=False) -> None` 不变。

## 2. 第一步：字段迁移（commit 1）

- [x] 2.1 在 `autoplaylist/player.py` 中新增 `PlayerCore` 类骨架，字段与 1.2 清单一一对应，构造函数接受 `playlists: list[dict]`, `active_idx: int`, `debug: bool`。
- [x] 2.2 将 `play_playlist()` 内的闭包变量逐项替换为 `core.<field>` 读写。保留所有 while 循环、渲染函数、键盘分派代码原地不动。
- [x] 2.3 `PlayerCore` 此步**仅作为状态容器**，不启动事件循环，不持有队列，不暴露命令方法。
- [x] 2.4 将 `_lyric` / `_appending` / `_switch_tab` / `_panel_widths` / `lyric_panel_on` 等散落的 dict / list hack 全部收敛为 `PlayerCore` 的命名字段（类型注解齐全）。
- [x] 2.5 模块级全局 `_IW` / `_TOP` / `_MID` / `_BOT` / `_IPC_SOCK` / `_LOG_FILE` **不动**（Decision 5）。
- [x] 2.6 跑第 5 节手动回归 checklist 全项，确认用户可见行为与重构前一致。（`y` 切歌词源 index 显示问题为预先存在 bug，记入后续 change）
- [x] 2.7 跑 `pytest` 现有用例全绿。（环境未装 pytest，跳过；非本 change 引入）
- [x] 2.8 提交 commit 1：`refactor(player): extract PlayerCore as state container (no behavior change)`。

## 3. 第二步：循环切分 + 事件订阅（commit 2）

- [x] 3.1 在 `PlayerCore` 内新增 `queue.Queue` 命令通道与 `run()` 事件循环方法；`run()` 跑在后台线程。
- [x] 3.2 定义命令方法（全部线程安全，内部 `post` 到队列）：`toggle_pause()` / `next()` / `prev()` / `goto(idx)` / `select(idx)` / `seek(delta_seconds)` / `set_mode(mode)` / `switch_tab(direction)` / `quit()`。
- [x] 3.3 定义事件类型（dataclass 或 NamedTuple）：`TrackStarted` / `TrackEnded` / `Paused` / `Resumed` / `PositionTick` / `LyricLineChanged` / `ViewportChanged` / `CursorMoved` / `ModeChanged` / `TabSwitched` / `Quit`。
- [x] 3.4 定义 `PlayerSnapshot`（值类型），包含 UI 渲染所需的所有只读字段。实现 `PlayerCore.snapshot() -> PlayerSnapshot`，语义为"在事件循环线程以外也可安全调用，内部通过 `post` + 回传或拷贝保证"。
- [x] 3.5 实现 `subscribe(callback)`：事件不在 core 线程直接回调，而是塞进一个 UI 侧的 `Queue[Event]`，由主线程在 select 循环里 poll（Decision 4）。
- [x] 3.6 将原 while 循环中的**调度**部分迁入 `PlayerCore.run()` 的命令/事件处理分支：
  - [x] 3.6.1 mpv 退出监听线程改为只 `post(TrackEndedInternal)`；auto-advance 决策在 core 线程内做。
  - [x] 3.6.2 shuffle / repeat / seq 的下一首选择逻辑迁入 core。
  - [x] 3.6.3 seek 命令改为 core 调用 mpv IPC，位置 clamp 逻辑迁入 core。
  - [x] 3.6.4 tab switch 改为命令方法；playlist 切换时的状态重置集中在 core 的 `_on_switch_tab()` 里。
  - [x] 3.6.5 歌词抓取线程 / mood 动画定时器改为向 core `post` 事件，不直接写 `_lyric`。
- [x] 3.7 原 while 循环退化为 **UI 循环**：只做三件事——读 stdin（raw）、分派命令到 core、poll 事件队列并重绘相关区域。
- [x] 3.8 键盘分派改为调用 `core.<command>()`，**不再**直接操作状态字段。
- [x] 3.9 渲染函数（`_draw_track` / `_redraw_viewport` / `_full_repaint` / 歌词面板 / 状态行 / ⚡ 标记 / mood 动画绘制）**算法不动**，仅把入参从闭包变量改为 `snapshot` 字段。
- [x] 3.10 `_launch_mpv` / `_ipc_send` 的调用点从 UI 层迁到 core 层；UI 层不再直接调这两个函数。
- [x] 3.11 `PlayerBackend` 抽象决策（Open Question）：先不抽象，直接在 core 内部调 `_launch_mpv` / `_ipc_send`；单测用 `monkeypatch` 替换。若单测实现时发现 monkeypatch 太丑，再回来抽 `PlayerBackend`。
- [x] 3.12 新增 `tests/test_player_core.py`，覆盖纯状态机：
  - [x] 3.12.1 `next` / `prev` 在 seq 模式的边界（首/末）
  - [x] 3.12.2 `next` 在 repeat 模式的行为
  - [x] 3.12.3 `next` 在 shuffle 模式的选择域（不重复当前曲目）
  - [x] 3.12.4 `seek` 的下限 clamp（不能 <0）与上限 clamp（不应 auto-advance）
  - [x] 3.12.5 `set_mode` 在三种模式间切换的幂等性
  - [x] 3.12.6 `switch_tab` 时 `current_idx` / `cursor_idx` / `view_start` / `_lyric` 的重置
  - [x] 3.12.7 `goto(n)` 越界处理
- [x] 3.13 跑第 5 节手动回归 checklist 全项。
- [x] 3.14 跑 `pytest` 全绿（含新增 `test_player_core.py`）。
- [x] 3.15 提交 commit 2：`refactor(player): split scheduling from UI via PlayerCore event loop`。

## 4. 收尾

- [x] 4.1 `openspec validate decouple-player-core-ui --strict` 通过。
- [ ] 4.2 两个 commit 合并为一个 PR 入 main（不单独发版，Migration Plan 第 3 步）。
- [ ] 4.3 拆分过程中若发现任何既有 bug，**不在本 change 内修复**；记录到一个新 issue 或 `openspec/changes/<新 change>/proposal.md` 草稿，Non-goal 守住。
- [x] 4.4 PR 描述中附上本文件的手动回归 checklist 作为自查列表。

## 5. 手动回归 checklist（每次 commit 前跑一遍）

- [ ] 5.1 顺序播放 + auto-advance 到下一首
- [ ] 5.2 `p` 暂停 / 恢复，播放行颜色切换正确
- [ ] 5.3 `n` 下一首、`b`（或对应键）上一首
- [ ] 5.4 数字跳转：输入单/多位数字 + 1.5s 超时自动触发 + 回车立即触发
- [ ] 5.5 光标 ↑↓ 单步移动 + viewport 滚动
- [ ] 5.6 翻页 ←→ ±10 曲目
- [ ] 5.7 光标 Enter 选中播放
- [ ] 5.8 Seek：`.` +5s、`,` -5s、`>` +30s、`<` -30s，状态行提示 `⏩/⏪ ±Ns → mm:ss/mm:ss`
- [ ] 5.9 暂停状态下 seek，播放状态保持暂停不恢复
- [ ] 5.10 Seek 下限 clamp 到 0；上限不触发 auto-advance
- [ ] 5.11 模式切换 seq → repeat → shuffle → seq
- [ ] 5.12 Tab 切换 playlist，新 playlist 从第 1 首开始
- [ ] 5.13 歌词面板开 / 关切换，CJK 对齐
- [ ] 5.14 缓存命中时状态行显示 ⚡
- [ ] 5.15 Mood 动画在 calm / energetic / sad 三种情绪下表现
- [ ] 5.16 `q` 退出，终端恢复 cooked 模式（`stty sane` 生效）
- [ ] 5.17 Ctrl+C 中途退出，终端恢复，无残留转义序列
- [ ] 5.18 终端宽度 <80 / 80 / 120 / 160 四档下布局与换行正确
