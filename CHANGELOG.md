# 更新日志 / Changelog

本文件记录当前维护分支的重要功能、修复、配置、部署与文档变更。
This file records important feature, fix, configuration, deployment, and documentation changes for the current maintained branch.

## 2026-05-07

- 修复 / Fixed: 普通任务调度器在执行失败时不再只输出 `INFO` 级别的"执行结束"日志，而是正确输出 `ERROR` 并携带错误详情；同时增加异常边界捕获，防止逃逸异常丢失在 APScheduler 层 / Log regular task scheduling failures at `ERROR` level with error details instead of a generic `INFO` completion message, and add an outer exception boundary so escaped errors are also captured.
- 修复 / Fixed: 签到任务 `_save_run_info` 中的调试 `print` 替换为 `logger.error`，确保保存历史文件或更新 `config.json` 失败时错误信息能写入 `app.log` / `error.log` 而不是仅输出到 stdout / Replace debug `print` statements in `_save_run_info` with `logger.error` so file I/O failures are persisted to the application log files rather than lost to stdout.
- 修复 / Fixed: 签到任务 `run_task_with_logs` 收尾阶段将 `_save_run_info` 与 `dispatch_notification` 的异常处理分离，确保保存失败不影响通知发送，通知失败也不覆盖已保存的历史记录，原始错误信息始终保留并返回给调用者 / Separate exception handling in the sign task cleanup phase so history-save failures do not block notification delivery, notification failures do not overwrite persisted history, and the original error is always preserved.

## 2026-05-05

- 修复 / Fixed: Dashboard 运行日志移除机器人回复展示，仅保留任务完成状态；文案由"最近 N 条记录"改为"近 3 天记录"；统一 Dashboard、任务列表与账号任务三处历史弹窗的时间与任务名字号，并将时间颜色从 `ui-muted` 调深为 `text-main/70`，提升可读性 / Remove bot-reply display from dashboard run logs and keep only the completion status; change the log summary label from "last N entries" to "last 3 days"; unify timestamp and task-name font sizes across dashboard, sign-tasks, and account-tasks history modals, and deepen timestamp color from `ui-muted` to `text-main/70` for better readability.

## 2026-05-05

- 修复 / Fixed: 修复右下角 Toast 通知的 CSS 主题选择器错误（`data-theme` 实际设置在 `body` 而非 `:root` 上，导致浅色模式下深色样式错误生效），并移除消息文字上强制覆盖颜色的内联样式，恢复按通知类型区分的主题色文字，确保深浅色主题下文字与背景对比度始终正确 / Fix the toast CSS theme selector bug where the dark-mode style was incorrectly applied in the light theme because `data-theme` lives on `body`, not `:root`; remove the inline color override on toast text so type-specific theme colors are restored and contrast remains correct in both themes.
- 修复 / Fixed: 账号日志与任务历史中“最新消息”摘要改为取结构化消息事件列表的第一条，与事件入库顺序保持一致 / Use the first structured message event as the "latest message" summary in account logs and task history to match the event insertion order.

## 2026-05-02

- 修复 / Fixed: `ADMIN_USERNAME` 现在会在首次初始化管理员时覆盖默认用户名，并补充 Docker 与 README 说明，明确初始管理员环境变量只在用户表为空时生效 / Honor `ADMIN_USERNAME` when creating the initial administrator and document that initial admin environment variables apply only while the user table is empty.

## 2026-05-01

- 修复 / Fixed: 任务历史日志会将“开始执行”动作流程框解析为结构化卡片，避免中文、emoji 与框线字符混排导致表格错位 / Render sign-task action-flow banners as structured cards in history logs so Chinese text, emoji, and box-drawing characters no longer misalign.

## 2026-04-29

- 修复 / Fixed: 提高右下角 Toast 提示在浅色主题下的清晰度，移除模糊背景叠加并增强错误提示图标、正文和关闭按钮对比度 / Improve bottom-right toast readability in the light theme by removing the blurred translucent background layer and increasing contrast for error icons, text, and the close button.

## 2026-04-28

- 修复 / Fixed: 前端重复点击同一个签到任务时，后台返回“正在执行中 / 请勿重复触发”后改为信息提示，不再误显示为执行失败 / Treat duplicate sign-task submissions that report an already-running task as informational UI feedback instead of a failure toast.
- 修复 / Fixed: 签到任务运行监控状态面板不再把仍在运行的重复触发状态渲染为失败样式，并恢复结构化消息事件中“发送消息 / Message sent”的翻译键 / Avoid rendering duplicate-running sign-task monitor states as failures and restore the sent-message translation key for structured message event labels.

## 2026-04-26

- 新增 / Added: 手动执行签到任务改为后台提交，接口立即返回提交状态，前端通过实时进度和历史链式日志查看完整执行过程 / Submit manual sign tasks to an in-process background runner so the API returns immediately while the UI follows progress through live status and historical flow logs.
- 新增 / Added: 签到任务后台执行增加中文阶段状态、同账号同任务去重、同账号不同任务排队等待提示，并展示前序任务、前序阶段、最后进度和等待时长 / Add Chinese phase status, duplicate protection for the same account-task pair, queued same-account task hints, and blocking task details including phase, latest progress, and wait duration.
- 修复 / Fixed: 账号锁等待超时只取消当前等待任务并写入失败历史，不中断前序任务；历史默认保留条数继续使用 `SIGN_TASK_HISTORY_MAX_ENTRIES=100` / Cancel only the waiting job on account-lock timeout, persist failure history without interrupting the blocking job, and keep the default history retention at `SIGN_TASK_HISTORY_MAX_ENTRIES=100`.

- 修复 / Fixed: 统一首页运行日志中“收到 N 条消息”和“最近消息”的字号字重，并移除账号任务历史展开后的重复“最新摘要”行 / Align the dashboard run-log count and latest-message typography, and remove the duplicate latest-summary line from expanded account task history entries.
- 修复 / Fixed: 优化浅色主题下任务卡片、任务历史、运行监控、首页日志与设置页的成功/失败状态样式，改用主题感知的高对比度状态色和历史面板背景，并为 9-11px 小字号文案增加 12px 可读下限，避免成功徽章、日志文字和说明文字发虚或看不清 / Improve light-theme readability for success/failure states across task cards, task history, run monitoring, dashboard logs, and settings by using theme-aware high-contrast status colors and history panel surfaces, and add a 12px readability floor for 9-11px text.

## 2026-04-25

- 变更 / Changed: 重构后端与 `tg_signer` 日志系统，统一时间戳与格式化输出，补充中文诊断日志、调度日志和关键边缘场景判断，并清理遗留 `print` 与 `utcnow()` 用法，便于直接通过日志定位失败阶段与原因 / Refine backend and `tg_signer` logging with unified timestamps and formatting, richer Chinese diagnostics, scheduler logs, defensive edge-case checks, and cleanup of legacy `print` and `utcnow()` usage so failures can be located directly from logs.
- 修复 / Fixed: 修复签到任务通知摘要误回退为启动日志的问题，补齐发送型及旧版配置签到任务的消息上下文采集，并避免复用旧的 no_updates client 或将自己发送的消息误记为执行摘要 / Fix sign task notifications falling back to startup logs, restore message context capture for send-type and legacy-config sign tasks, and avoid stale no_updates client reuse or self-authored messages being picked as summaries.
- 修复 / Fixed: 修正签到任务消息历史中的发送方/接收方建模与展示，私聊场景不再把 chat 误显示为接收者，并补充名称、用户名与 ID 的可读格式 / Correct sender and recipient modeling for sign task message history so private chats no longer display the chat object as the recipient, and show readable name, username, and ID formatting.

## 2026-04-24

- 新增 / Added: 普通任务与签到任务支持通过 Telegram 官方 Bot 发送完成通知，支持全局默认配置与账号级覆盖 / Add Telegram Bot completion notifications for regular and sign tasks with global defaults and per-account overrides.
- 变更 / Changed: Telegram 完成通知配置完全通过 UI 管理，不依赖新增 Docker 环境变量 / Manage Telegram completion notification settings entirely from the UI without new Docker environment variables.
- 新增 / Added: 签到任务运行监控支持结构化 Telegram 消息事件实时推送与历史回看 / Add structured Telegram message event streaming and history review for sign task monitoring.
- 变更 / Changed: 签到任务历史 JSON 新增 `message_events` 字段，并保持旧历史记录兼容读取 / Extend sign task history JSON with `message_events` while remaining compatible with legacy records.
- 新增 / Added: 增加 `SIGN_TASK_HISTORY_MAX_MESSAGE_EVENTS` 运行时配置，用于限制单次执行保留的结构化消息事件数量，并支持设为 `0` 禁用历史保留 / Add `SIGN_TASK_HISTORY_MAX_MESSAGE_EVENTS` runtime config to cap structured message events kept per run and allow `0` to disable history retention.

## 2026-04-23

- 修复 / Fixed: 避免已编辑回复消息场景下的按钮点击出现延迟 / Avoid delayed button clicks on edited reply messages.
- 修复 / Fixed: 修复任务图标、进度指示和主题相关的界面问题 / Fix UI task icons, progress indicators, and theme-related issues.
- 变更 / Changed: 将动作间隔配置统一迁移为毫秒单位 / Migrate action interval configuration to milliseconds.
- 新增 / Added: 增加任务重命名，以及取消或重置表单能力 / Add task rename support and cancel or reset form behavior.
- 新增 / Added: 增加签到任务批量导入与导出能力 / Add batch sign task import and export.
- 修复 / Fixed: 修复 Telegram API 首次启动时的环境变量引导优先级 / Fix Telegram API environment bootstrap precedence on first run.

## 2026-04-22

- 变更 / Changed: 刷新部署文档，并补充 Telegram client 设备参数统一配置 / Refresh deployment docs and unify Telegram client device configuration.
