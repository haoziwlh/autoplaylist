## ADDED Requirements

### Requirement: Player core and terminal UI SHALL be decoupled
The playback session SHALL be implemented as two separable concerns: a **player core** that owns all mutable playback state and drives the playback lifecycle, and a **terminal UI** that renders state and translates keyboard input into commands. The terminal UI SHALL NOT mutate playback state directly; all mutations SHALL go through command methods exposed by the player core.

This requirement is an architectural constraint. Outward user-visible behavior (keys, rendering, timing, status line, lyrics panel, cache markers, mood animation) MUST remain unchanged relative to the prior implementation.

#### Scenario: State ownership
- **WHEN** any playback-related mutable field is read or written (current track index, cursor index, paused flag, play mode, viewport start, lyric state, active playlist, mpv/yt-dlp handles)
- **THEN** the field SHALL live on the player core, not in terminal UI code or module-level mutable state
- **THEN** only the player core's internal event loop SHALL write to these fields

#### Scenario: UI drives core via commands, not shared references
- **WHEN** a key press maps to a playback action (pause / next / prev / goto / select / seek / mode change / tab switch / quit)
- **THEN** the terminal UI SHALL invoke a command method on the player core
- **THEN** the terminal UI SHALL NOT hold or mutate any reference that bypasses command methods

#### Scenario: UI renders from snapshots and events
- **WHEN** the terminal UI needs to draw or update any region
- **THEN** it SHALL read an immutable snapshot from the player core, or react to an event delivered by the player core's subscription mechanism
- **THEN** rendering SHALL NOT depend on direct access to the core's live mutable fields

#### Scenario: Behavior parity with prior implementation
- **WHEN** a user interacts with the player through any documented keybinding or waits for any automatic behavior (auto-advance, shuffle selection, repeat, lyric marquee, mood animation, cache ⚡ marker, seek clamp, terminal-width adaptation)
- **THEN** the observable outcome SHALL be identical to the implementation that existed immediately before this change landed
- **THEN** no keybinding, visual element, timing characteristic, or status line text SHALL be added, removed, or altered as part of this change

#### Scenario: Core lifecycle is testable without a terminal
- **WHEN** unit tests exercise the player core's state transitions (next / prev / goto / shuffle / repeat / seek clamp / mode change / tab switch)
- **THEN** the tests SHALL be able to run without allocating a TTY, without launching mpv, and without writing ANSI sequences to stdout
- **THEN** the tests SHALL drive the core through its public command methods and assert on snapshot or event output
