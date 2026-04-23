# TG-AutoSign

[English README](README_EN.md) | [更新日志](CHANGELOG.md)

TG-AutoSign 是一个面向 Telegram 自动化任务的管理面板与运行时项目。它支持多账号管理、自动签到、消息发送、按钮点击、日志可视化，以及 AI 能力接入，适合在本地环境、VPS 或 Docker 容器中长期运行。

> 当前仓库在原有项目基础上继续维护，全程由 GitHub Copilot 开发与整理，并补充了面板化、容器化、设备参数统一化与部署说明。

## 最近更新

完整历史见 [CHANGELOG.md](CHANGELOG.md)。

- 2026-04-23 修复已编辑回复消息场景下的按钮点击延迟
- 2026-04-23 修复任务图标、进度指示和主题相关 UI 问题
- 2026-04-23 将动作间隔配置统一迁移为毫秒
- 2026-04-23 增加任务重命名与取消或重置表单能力
- 2026-04-23 增加签到任务批量导入与导出能力
- 2026-04-23 修复 Telegram API 首次启动时的环境变量引导优先级

## 项目能力

- 多账号 Telegram 管理
- 自动签到、定时消息、按钮点击等任务动作
- AI 识图、AI 计算题等自动化动作
- Web 面板查看执行日志、历史记录与账号状态
- Docker / Docker Compose / GHCR 工作流支持
- 自定义 Telegram Client 设备参数，便于统一部署环境

## 快速开始

默认管理账号：

- 用户名：`admin`
- 密码：如果未设置 `ADMIN_PASSWORD`，默认会创建为 `admin123`

首次登录后请立即修改密码。

### 方式一：通过 Docker 命令启动

最直接的启动方式就是直接运行镜像：

```bash
docker run -d \
  --name tg-autosign \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e APP_SECRET_KEY=your_secret_key \
  -e ADMIN_PASSWORD=change_me \
  ghcr.io/lyc1466/tg-autosign:latest
```

如果你使用反向代理，建议仅监听本机：

```bash
-p 127.0.0.1:8080:8080
```

启动后访问：`http://你的服务器IP:8080`

### 方式二：通过 Docker Compose 启动

仓库内已经提供两份 Compose 文件：

- `docker-compose.yml`：简洁版，只保留最常用的基础部署项，适合直接启动
- `docker-compose.full.yml`：全量注释版，按当前配置体系补全所有仍然使用环境变量的运行项，适合二次定制

使用简洁版：

```bash
docker compose up -d
```

使用全量注释版：

```bash
docker compose -f docker-compose.full.yml up -d
```

补充说明：

- 至少要修改 `APP_SECRET_KEY`，建议同时修改 `ADMIN_PASSWORD`
- Telegram API、AI 配置、数据目录现在统一在 `UI -> 系统设置` 中维护，所以 Compose 里故意不再写这些项
- 如果你只想快速上线，优先使用 `docker-compose.yml`
- 如果你需要共享代理、设备参数、任务调度细项或安全加固配置，再改 `docker-compose.full.yml`

启动后访问：`http://你的服务器IP:8080`

### 方式三：下载源码运行

如果你希望直接运行源码，建议按下面的顺序操作：

```bash
git clone https://github.com/lyc1466/TG-AutoSign.git
cd TG-AutoSign
```

1. 按 `.env.example` 准备环境变量
  如果你直接在 shell 中启动，也可以手动导出这些变量
  `APP_SECRET_KEY` 在实际运行时必须设置
2. 安装 Python 依赖
3. 安装前端依赖并构建前端静态资源
4. 启动后端服务

一个常见流程示例：

```bash
pip install -e .
cd frontend
npm install
npm run build
cd ..
uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

启动后访问：`http://你的服务器IP:8080`

## 构建卡顿时使用代理

如果 `docker build` 在依赖下载阶段卡顿，可尝试：

```bash
docker build \
  --build-arg HTTP_PROXY=http://127.0.0.1:7890 \
  --build-arg HTTPS_PROXY=http://127.0.0.1:7890 \
  -t tg-autosign .
```

## 数据目录与权限

- 默认数据目录：`/data`
- 如果 `/data` 不可写，当前实现会回退到 `/tmp/tg-signpulse`（非持久化）
- 容器内运行时会尽量适配挂载目录权限，但仍建议确保挂载卷可写

可在容器内快速排查：

```bash
id
ls -ld /data
touch /data/.probe && rm /data/.probe
```

## 健康检查

- `GET /healthz`：快速健康检查
- `GET /readyz`：服务就绪检查

## 项目结构

```text
backend/      FastAPI 后端、调度与 API
tg_signer/    Telegram 自动化核心与 CLI
frontend/     Next.js 管理面板
docker/       容器入口脚本
tools/        辅助工具脚本
```

## 统一后的配置优先级

当前版本已经把运行时配置收口到统一入口。部署时请按下面的顺序理解“谁覆盖谁”：

1. 大多数基础运行项，仍然是容器或进程环境变量优先。
2. 少数持久化配置按各自规则读取，典型例子是 Telegram API、AI 配置和数据目录。
3. 对应来源都没有值时，才回退到代码默认值。

重点规则：

- Telegram API 凭证优先级为 `.telegram_api.json` > `TG_API_ID` / `TG_API_HASH` > 项目内置默认凭证。适合首次启动先用环境变量注入，后续在 UI 中改完后直接以 UI 为准。
- AI 配置统一从 `.openai_config.json` 读取；如果 UI 未配置，AI 功能视为未启用。
- 数据目录最终取 `APP_DATA_DIR_OVERRIDE_FILE` 指向的覆盖文件内容；未设置时默认 `/data`。
- 单次任务或登录显式传入的代理 > 账号代理 > `TG_PROXY`。
- `TG_SESSION_NO_UPDATES` > `TG_NO_UPDATES`（兼容别名）。
- `APP_*`、`SIGN_TASK_*`、`TG_DEVICE_*`、`TG_SIGNER_*` 这类基础运行时参数主要只读环境变量，面板不会反向覆盖。
- `NEXT_PUBLIC_API_BASE` 是前端构建期变量，修改后需要重新构建前端资源或镜像。

## 全部环境变量

以下内容与 `.env.example` 保持一致，建议部署时按需配置。

### 运行环境

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | API 监听地址；反向代理或容器直连时可改为 `0.0.0.0` |
| `PORT` | `8080` | 后端容器监听端口 |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `APP_TIMEZONE` | `Asia/Shanghai`（可选） | 面板调度时区，默认继承 `TZ` |
| `APP_DATA_DIR_OVERRIDE_FILE` | `.tg_signpulse_data_dir` | 数据目录覆盖文件路径，高级选项；用于指定 UI 数据目录配置保存在哪个文件 |
| `APP_DB_PATH` | `/data/db.sqlite` | SQLite 数据库文件路径，高级选项 |
| `APP_SIGNER_WORKDIR` | `/data/.signer` | 签到任务工作目录，高级选项 |
| `APP_SESSION_DIR` | `/data/sessions` | Telegram session 存储目录，高级选项 |
| `APP_LOGS_DIR` | `/data/logs` | 应用日志目录，高级选项 |

### 安全与登录

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `APP_APP_NAME` | `tg-signer-panel` | 面板应用名称 |
| `APP_SECRET_KEY` | `your_secret_key_here` | 面板密钥，强烈建议显式设置 |
| `APP_ACCESS_TOKEN_EXPIRE_HOURS` | `12` | 登录令牌有效期（小时） |
| `ADMIN_PASSWORD` | `change_me`（可选） | 初始管理员密码；未设置时默认 `admin123` |
| `APP_TOTP_VALID_WINDOW` | `1`（示例） | 2FA TOTP 时间窗口容差 |

### Telegram / Pyrogram

Telegram API 支持“初次启动先用环境变量，后续 UI 保存后以 UI 为准”的模式，优先级为 `.telegram_api.json` > `TG_API_ID` / `TG_API_HASH` > 内置默认值。

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `TG_API_ID` | `123456`（示例） | Telegram API ID；当 UI 还未保存 Telegram API 配置时，用于初次启动注入 |
| `TG_API_HASH` | `your_api_hash_here` | Telegram API Hash；当 UI 还未保存 Telegram API 配置时，用于初次启动注入 |
| `TG_PROXY` | `socks5://127.0.0.1:1080` | 共享代理地址 |
| `TG_DEVICE_MODEL` | `Samsung Galaxy S24` | 自定义设备型号 |
| `TG_SYSTEM_VERSION` | `SDK 35` | 自定义系统版本 |
| `TG_APP_VERSION` | `11.4.2` | 自定义客户端版本 |
| `TG_LANG_CODE` | `zh` | 语言代码 |
| `TG_SESSION_MODE` | `file` | Session 存储模式，支持 `file` / `string` |
| `TG_SESSION_NO_UPDATES` | `0` | 是否关闭更新接收 |
| `TG_NO_UPDATES` | `0` | `TG_SESSION_NO_UPDATES` 的兼容别名 |
| `TG_GLOBAL_CONCURRENCY` | `1` | 全局并发数 |

### 签到 / 任务调度

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `SIGN_TASK_ACCOUNT_COOLDOWN` | `5` | 同账号任务冷却秒数 |
| `SIGN_TASK_FORCE_IN_MEMORY` | `0` | 是否强制使用内存模式 |
| `SIGN_TASK_HISTORY_MAX_ENTRIES` | `100` | 单任务历史条数上限 |
| `SIGN_TASK_HISTORY_MAX_FLOW_LINES` | `200` | 单次日志流保留行数上限 |
| `SIGN_TASK_HISTORY_MAX_LINE_CHARS` | `500` | 单行日志字符上限 |

### AI 配置

AI 配置现统一在 `系统设置 -> AI 配置` 中维护；CLI 场景可通过 `tg-signer llm-config` 写入同一份持久化配置文件。

### 前端构建变量

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `/api` | 前端请求 API 的基础路径 |

### 面板 / CLI 辅助变量

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `TG_SIGNER_WORKDIR` | `.signer` | CLI 工作目录 |
| `TG_ACCOUNT` | `my_account` | 当前账号名 |
| `TG_SESSION_STRING` | `...` | 字符串会话 |
| `TG_SIGNER_GUI_AUTHCODE` | `...` | GUI 授权码 |
| `SERVER_CHAN_SEND_KEY` | `...` | Server酱推送密钥 |

### 日志

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `PYROGRAM_LOG_ON` | `0` | 是否开启 Pyrogram 日志 |

## 自定义数据目录

当前数据目录由 UI 管理：

1. 面板设置：`系统设置 -> 全局设置 -> 数据目录`
2. 高级场景可用 `APP_DATA_DIR_OVERRIDE_FILE` 改变这份 UI 配置保存到哪个文件

补充说明：

- 面板设置实际会写入数据目录覆盖文件。
- 如果从未在 UI 中设置过，运行时默认数据目录仍是 `/data`。

建议：

- 修改后重启服务
- 目录必须可写
- 生产环境请挂载持久化卷

## 致谢

本项目在以下项目基础上进行了复刻、重构与扩展，感谢原作者与社区贡献：

- [TG-SignPulse](https://github.com/akasls/TG-SignPulse.git)
- [tg-signer](https://github.com/amchii/tg-signer.git)
