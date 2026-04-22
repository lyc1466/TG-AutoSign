# TG-AutoSign

[English README](README_EN.md)

TG-AutoSign 是一个面向 Telegram 自动化任务的管理面板与运行时项目。它支持多账号管理、自动签到、消息发送、按钮点击、日志可视化，以及 AI 能力接入，适合在本地环境、VPS 或 Docker 容器中长期运行。

> 当前仓库在原有项目基础上继续维护，并补充了面板化、容器化、设备参数统一化与部署说明。

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

你也可以自己写一个 `docker-compose.yml`，例如：

```yaml
services:
  app:
    image: ghcr.io/lyc1466/tg-autosign:latest
    container_name: tg-autosign
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      - PORT=8080
      - APP_DATA_DIR=/data
      - TZ=Asia/Shanghai
      - APP_SECRET_KEY=your_secret_key
      - ADMIN_PASSWORD=change_me
```

保存后执行：

```bash
docker compose up -d
```

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

## 全部环境变量

以下内容与 `.env.example` 保持一致，建议部署时按需配置。

### 运行环境

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | API 监听地址；反向代理或容器直连时可改为 `0.0.0.0` |
| `APP_PORT` | `3000`（示例） | 面板模式端口，仅 panel 示例常用 |
| `PORT` | `8080` | 后端容器监听端口 |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `APP_TIMEZONE` | `Asia/Shanghai`（可选） | 面板调度时区，默认继承 `TZ` |
| `APP_DATA_DIR` | `/data` | 数据目录 |
| `APP_DATA_DIR_OVERRIDE_FILE` | `.tg_signpulse_data_dir` | 数据目录覆盖文件路径，高级选项 |
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

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `TG_API_ID` | `123456`（示例） | Telegram API ID |
| `TG_API_HASH` | `your_api_hash_here` | Telegram API Hash |
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

| 变量 | 默认值 / 示例 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | `sk-...` | 启用 AI 功能所需 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容接口地址 |
| `OPENAI_MODEL` | `gpt-4o` | 默认模型 |

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

可通过两种方式设置：

1. 面板设置：`系统设置 -> 全局设置 -> 数据目录`
2. 环境变量：`APP_DATA_DIR=/your/path`

建议：

- 修改后重启服务
- 目录必须可写
- 生产环境请挂载持久化卷

## 致谢

本项目在以下项目基础上进行了复刻、重构与扩展，感谢原作者与社区贡献：

- [TG-SignPulse](https://github.com/akasls/TG-SignPulse.git)
- [tg-signer](https://github.com/amchii/tg-signer.git)
