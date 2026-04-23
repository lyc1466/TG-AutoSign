# 更新日志 / Changelog

本文件记录当前维护分支的重要功能、修复、配置、部署与文档变更。
This file records important feature, fix, configuration, deployment, and documentation changes for the current maintained branch.

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
