## Context

当前 `autoplaylist/player.py` 约 1700 行，核心入口 `play_playlist()` 一个函数就承担了：

1. **播放状态**：`current_idx` / `cursor_idx` / `paused` / `play_mode` / `view_start` / `_lyric` / `_appending` / `_switch_tab` 等散落在闭包里的可变变量。
2. **播放调度**：启动 yt-dlp + mpv、监听 mpv 退出、自动推进、shuffle / repeat、seek、tab 切换。
3. **TUI 渲染**：`_draw_track` / `_redraw_viewport` / `_full_repaint` / 歌词面板绘制 / 状态行 / cache ⚡ 标记 / mood 动画。
4. **键盘输入**：stdin raw 模式、按键分派、数字跳转缓冲、箭头键解析。

所有状态都是闭包里的 `nonlocal` 和 `list[0]` hack，调度与渲染在同一个 while 循环里交错。任何新演进（后台化、状态栏投影、外部命令控制）都无处下手——这是本次重构的直接动因。

mpv 已经以 `--input-ipc-server=<sock>` 启动，命令通道天然存在；歌词、进度、mood 都有独立后台线程。底层异步模型其实是健康的，烂在**最外层那个超长函数没有边界**。

## Goals / Non-Goals

**Goals:**
- 抽出一个 `PlayerCore` 类（单线程事件循环 + 若干后台线程），独占播放状态和 mpv 生命周期，对外只暴露命令方法和事件订阅。
- TUI 代码（按键解析 + 渲染）成为 `PlayerCore` 的**唯一**消费者，通过命令方法驱动 core，通过快照 + 事件刷新画面。
- `play_playlist(playlists, active_idx, debug)` 签名保持不变；`_commands.py` / `cli.py` 的调用点零修改。
- 用户可见行为（按键、视觉、时序、⚡ 标记、mood 动画、tab 切换、seek 限位等）与重构前**逐项一致**。
- 为 `PlayerCore` 增加最小单测（纯状态机：next / prev / shuffle / mode 切换 / seek clamp），确保后续演进有回归网。

**Non-Goals:**
- 不做 daemon / fork / setsid / 任何进程脱离终端的改动。
- 不新增子命令（`autoplaylist next` 等），不新增 IPC 通道。
- 不修改 mpv 启动方式、yt-dlp 管线、缓存策略、歌词源。
- 不做任何 UI 视觉调整（包括"最小化"视图）。
- 不顺手修拆分过程中发现的既有 bug；发现即记录，单独开 change。
- 不引入新依赖（不上 asyncio / rich / textual / prompt_toolkit）。保持 raw ANSI + threading 现状。

## Decisions

### Decision 1：单线程事件循环 + 命令队列，而非多线程共享状态

**选择**：`PlayerCore` 内部维护一个 `queue.Queue[Command]`，主循环 `run()` 在一个线程内串行消费命令和内部事件（mpv 退出、歌词 tick、tab 切换请求）。所有状态字段只在这个循环线程内修改。其他线程（键盘读取、歌词抓取、mpv 退出监听、mood 动画定时器）通过 `post(cmd)` 往队列里塞事件，绝不直接改状态。

**理由**：
- 现状的 `nonlocal` + `list[0]` 本质就是在模拟共享可变状态，没有锁，仅靠"只有主循环改 / 后台线程只读"的不成文约定维持。这约定一旦被拆分打破就等于地雷阵。
- 单线程事件循环让"谁能改状态"这个问题有唯一答案，回归测试和后续的 daemon 化都友好。
- 不引入 asyncio：现有代码是阻塞风格 + `select`，asyncio 化的范围远超本次 change 的目标。`queue.Queue` 零依赖、零范式切换。

**备选**：
- *asyncio + Task*：范式翻转太大，超出 non-goals。
- *保留多线程 + 加锁*：锁的粒度很难一次性定对，容易死锁，收益不如单线程循环清晰。

### Decision 2：Core 对外只暴露命令方法 + 事件订阅，不暴露可变状态引用

**选择**：
- 命令方法（线程安全，内部就是 `post` 到队列）：`toggle_pause() / next() / prev() / goto(idx) / select(idx) / seek(delta) / set_mode(mode) / switch_tab(dir) / quit()`。
- 事件订阅：`subscribe(callback)`，事件类型包括 `TrackStarted / TrackEnded / Paused / Resumed / PositionTick / LyricLineChanged / ViewportChanged / CursorMoved / ModeChanged / TabSwitched / Quit`。
- 状态读取：`snapshot() -> PlayerSnapshot`（一个 dataclass / NamedTuple，值类型，拷贝而非引用）。TUI 渲染需要什么就从 snapshot 里取。

**理由**：
- 命令 / 事件 / 快照是 daemon 化之后可直接映射到 IPC 协议的三种基元，这次重构相当于免费铺好接口。
- 渲染层拿不到可变引用，就无法在"错误的线程、错误的时机"写坏状态。

**备选**：
- *暴露 `core.current_idx` 等属性*：简单，但重演了今天的耦合，拒绝。

### Decision 3：TUI 改造分"字段替换"和"结构拆分"两步

**选择**：`player.py` 内部重构，分两步串行进行，每步都必须能独立运行且用户行为不变：

1. **第一步：字段迁移**。把闭包里所有可变变量搬进 `PlayerCore`，但保留现有的 while 循环和渲染代码在 `play_playlist()` 里。循环改为读写 `core.<field>`。**此时 core 还不是事件循环**，只是一个状态容器——目的是先把"谁拥有状态"搞清楚。
2. **第二步：循环切分**。把 while 循环里的"调度"部分（mpv 退出、auto-advance、shuffle/repeat、seek、tab 切换）迁进 `PlayerCore.run()`，原 while 循环退化为"键盘输入 + 渲染"。键盘分派改为调用 `core.next()` 等命令方法；渲染改为订阅事件 + 读 snapshot。

**理由**：一步拆完 1700 行的可能性为零。两步之间有明确的"运行 + 回归验证"checkpoint，出问题能快速回退。每一步的 diff 都能被人读懂。

**备选**：
- *一次性重写*：diff 不可审、回归不可控，拒绝。

### Decision 4：键盘输入保留在主线程、stdin raw 模式不变

**选择**：继续用 `termios` + `tty.setraw` + `select` 读 stdin，放在 `play_playlist()` 的主线程。按键解析后调用 `core.<command>()`。`PlayerCore.run()` 跑在后台线程。

**理由**：
- stdin raw 模式对"谁拥有终端"敏感，放主线程最安全，和现状一致。
- 键盘线程只产生命令、不读状态，天然满足 Decision 1 的约束。
- 主线程同时跑渲染订阅回调（事件到来时重绘相关区域），避免 ANSI 写入出现跨线程交错。**事件订阅的 dispatch 必须 marshal 回主线程**（通过一个 `queue.Queue[Event]`，主线程在 select 的同一 loop 里 poll）。

### Decision 5：`_LOG_FILE` / `_IPC_SOCK` / `_IW` 等模块级全局暂不动

**选择**：模块级全局变量（`_IW` / `_TOP` / `_MID` / `_BOT` / `_IPC_SOCK` / `_LOG_FILE`）保持原样。仅将**可变的运行时状态**搬进 `PlayerCore`。

**理由**：这些是"进程级配置常量 + 进程级外部资源路径"，与"一次播放会话的状态"是不同层级。本次只拆后者。一次只做一件事。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 拆分引入光标定位 bug（现在依赖 `_lines_up` 等精确计算的行号） | 渲染逻辑在第二步只做"接线改造"，不改算法；所有 `\033[nA/nB` 相关函数原封不动迁入 TUI 模块 |
| tab 切换、歌词面板开关的状态重置路径散乱，容易漏迁 | 在第一步字段迁移时 grep `nonlocal` / `[0] =` 两类赋值点，逐一列表，作为 tasks 的勾选项 |
| 两步之间的中间态留在 main 分支风险 | 在同一个 change 下分两个 commit，合并时作为一个 PR；不单独发布版本；中间 commit 也必须手动跑一遍播放回归 |
| mpv 退出监听线程与新的事件循环之间竞态 | mpv 监听线程仅 `core.post(TrackEndedInternal)`，不直接改状态，由主事件循环在 `TrackEnded` 处理里决定是否 auto-advance |
| 回归难以自动化（终端 TUI 天生难测） | `PlayerCore` 的状态机部分（next / prev / shuffle / repeat / seek clamp / mode 切换 / tab 切换）以**不启动 mpv** 的方式单测（mpv 句柄抽象成一个可替换的 `PlayerBackend` 接口，测试里用 fake）；渲染回归靠手动 checklist |
| `PlayerBackend` 抽象可能被批"过度设计" | 只抽 5 个方法：`start(track) / stop() / toggle_pause() / seek(delta) / get_position()`。仅为测试存在，非为未来扩展 |

## Migration Plan

1. 第一步（字段迁移）落地 → 手动回归 checklist 通过 → commit。
2. 第二步（循环切分 + 事件订阅）落地 → 手动回归 checklist 通过 + `PlayerCore` 单测通过 → commit。
3. 两 commit 合并为一个 PR 入 main，版本号不单独发布（下次发版时附带）。
4. 回退策略：任一步出问题，直接 `git revert` 对应 commit；不做渐进修补。

**手动回归 checklist**（写进 tasks.md）：
- [ ] 顺序播放、auto-advance
- [ ] `p` 暂停 / 恢复，播放行颜色切换
- [ ] `n` / `b` 下一首 / 上一首
- [ ] 数字跳转 + 1.5s 超时 / 回车
- [ ] 光标 ↑↓、翻页 ←→
- [ ] Enter 选中播放
- [ ] `,` / `.` / `<` / `>` 四档 seek + 状态行提示 + 暂停时 seek 不恢复播放
- [ ] 模式切换 seq / repeat / shuffle
- [ ] Tab 切换 playlist
- [ ] 歌词面板开关 + CJK 对齐
- [ ] 缓存命中时 ⚡ 标记
- [ ] mood 动画（calm / energetic / sad）
- [ ] `q` 退出 + `stty sane` 恢复
- [ ] Ctrl+C 退出 + 终端状态恢复
- [ ] 终端宽度 <80 / 80 / >120 三档的布局

## Open Questions

- **`PlayerBackend` 抽象是否值得**：仅为单测存在。若评审认为现阶段不值得，可改为单测里 monkey-patch `_launch_mpv` + `_ipc_send`，`PlayerCore` 内部继续直接调现有函数。倾向前者（更干净），但接受后者（diff 更小）。在 tasks 里作为可选项保留决定窗口。
- **事件订阅的交付方式**：是主线程 poll 一个 `Queue[Event]`，还是 `PlayerCore` 在自己的线程里调用回调？前者安全但要求主循环加一条 select 分支；后者简单但要求回调里不碰终端 stdout。倾向前者（Decision 4 已定）。记录在此以便评审挑战。
- **`play_playlist()` 是否顺带改为 `run_player_session()`**：不改。保持对 `_commands.py` / `cli.py` 的零修改承诺。
