# TG-AutoSign

[中文说明](README.md)

TG-AutoSign is a Telegram automation project with a web management panel. It supports multi-account management, auto sign-in workflows, message and button actions, AI-assisted tasks, execution logs, and Docker-based deployment.

> This repository continues maintenance on top of earlier projects and adds panelization, containerization, unified client device parameters, and deployment guidance.

## Capabilities

- Manage multiple Telegram accounts in one place
- Automate sign-ins, scheduled messages, and button actions
- Use AI Vision and AI Calculate actions in workflows
- Inspect logs, history, and account states from a web panel
- Run with Docker, Docker Compose, and GHCR image publishing
- Unify Telegram Client device parameters for consistent deployments

## Quick Start

Default admin account:

- Username: `admin`
- Password: if `ADMIN_PASSWORD` is not set, the default password is `admin123`

Change the password immediately after first login.

### Method 1: Start with a Docker command

The most direct way is to run the image directly:

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

If you use a reverse proxy, bind locally only:

```bash
-p 127.0.0.1:8080:8080
```

Then visit: `http://YOUR_SERVER_IP:8080`

### Method 2: Start with Docker Compose

You can also write your own `docker-compose.yml`, for example:

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

After saving the file, run:

```bash
docker compose up -d
```

Then visit: `http://YOUR_SERVER_IP:8080`

### Method 3: Download the source code and run it

If you prefer running from source, a typical flow is:

```bash
git clone https://github.com/lyc1466/TG-AutoSign.git
cd TG-AutoSign
```

1. Prepare environment variables based on `.env.example`
  If you launch from a shell directly, you can export them manually
  `APP_SECRET_KEY` must be set for a real run
2. Install Python dependencies
3. Install frontend dependencies and build static assets
4. Start the backend service

A common example flow:

```bash
pip install -e .
cd frontend
npm install
npm run build
cd ..
uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

Then visit: `http://YOUR_SERVER_IP:8080`

## Build with Proxy When Downloads Stall

If `docker build` stalls during dependency downloads, try:

```bash
docker build \
  --build-arg HTTP_PROXY=http://127.0.0.1:7890 \
  --build-arg HTTPS_PROXY=http://127.0.0.1:7890 \
  -t tg-autosign .
```

## Data Directory and Permissions

- Default data directory: `/data`
- If `/data` is not writable, the current implementation falls back to `/tmp/tg-signpulse` (non-persistent)
- The container tries to adapt runtime permissions to the mounted volume, but the mounted path should still be writable

Useful checks inside the container:

```bash
id
ls -ld /data
touch /data/.probe && rm /data/.probe
```

## Health Checks

- `GET /healthz`: quick health check
- `GET /readyz`: readiness check

## Project Structure

```text
backend/      FastAPI backend, scheduler, and APIs
tg_signer/    Telegram automation core and CLI
frontend/     Next.js management panel
docker/       Container entry scripts
tools/        Helper scripts
```

## Full Environment Variables

The table below follows `.env.example`.

### Runtime

| Variable | Default / Example | Description |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | API bind address; use `0.0.0.0` for direct exposure or reverse proxy setups |
| `APP_PORT` | `3000` (example) | Port for panel-mode example |
| `PORT` | `8080` | Backend container port |
| `TZ` | `Asia/Shanghai` | Container timezone |
| `APP_TIMEZONE` | `Asia/Shanghai` (optional) | Panel scheduler timezone; defaults to `TZ` |
| `APP_DATA_DIR` | `/data` | Data directory |
| `APP_DATA_DIR_OVERRIDE_FILE` | `.tg_signpulse_data_dir` | Override file path for the data directory |
| `APP_DB_PATH` | `/data/db.sqlite` | SQLite database file path |
| `APP_SIGNER_WORKDIR` | `/data/.signer` | Task work directory |
| `APP_SESSION_DIR` | `/data/sessions` | Telegram session directory |
| `APP_LOGS_DIR` | `/data/logs` | Application logs directory |

### Security and Login

| Variable | Default / Example | Description |
|---|---|---|
| `APP_APP_NAME` | `tg-signer-panel` | Panel application name |
| `APP_SECRET_KEY` | `your_secret_key_here` | Panel secret key; strongly recommended to set |
| `APP_ACCESS_TOKEN_EXPIRE_HOURS` | `12` | Access token lifetime in hours |
| `ADMIN_PASSWORD` | `change_me` (optional) | Initial admin password; defaults to `admin123` if unset |
| `APP_TOTP_VALID_WINDOW` | `1` (example) | TOTP tolerance window for 2FA |

### Telegram / Pyrogram

| Variable | Default / Example | Description |
|---|---|---|
| `TG_API_ID` | `123456` (example) | Telegram API ID |
| `TG_API_HASH` | `your_api_hash_here` | Telegram API hash |
| `TG_PROXY` | `socks5://127.0.0.1:1080` | Shared proxy URL |
| `TG_DEVICE_MODEL` | `Samsung Galaxy S24` | Custom device model |
| `TG_SYSTEM_VERSION` | `SDK 35` | Custom system version |
| `TG_APP_VERSION` | `11.4.2` | Custom app version |
| `TG_LANG_CODE` | `zh` | Language code |
| `TG_SESSION_MODE` | `file` | Session storage mode: `file` or `string` |
| `TG_SESSION_NO_UPDATES` | `0` | Disable receiving updates |
| `TG_NO_UPDATES` | `0` | Backward-compatible alias of `TG_SESSION_NO_UPDATES` |
| `TG_GLOBAL_CONCURRENCY` | `1` | Global concurrency limit |

### Sign Tasks / Scheduling

| Variable | Default / Example | Description |
|---|---|---|
| `SIGN_TASK_ACCOUNT_COOLDOWN` | `5` | Cooldown seconds for the same account |
| `SIGN_TASK_FORCE_IN_MEMORY` | `0` | Force in-memory mode |
| `SIGN_TASK_HISTORY_MAX_ENTRIES` | `100` | Max history entries per task |
| `SIGN_TASK_HISTORY_MAX_FLOW_LINES` | `200` | Max flow log lines per run |
| `SIGN_TASK_HISTORY_MAX_LINE_CHARS` | `500` | Max characters per log line |

### AI

| Variable | Default / Example | Description |
|---|---|---|
| `OPENAI_API_KEY` | `sk-...` | Required to enable AI features |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `OPENAI_MODEL` | `gpt-4o` | Default AI model |

### Frontend Build

| Variable | Default / Example | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `/api` | Base path used by the frontend when calling APIs |

### Panel / CLI Helpers

| Variable | Default / Example | Description |
|---|---|---|
| `TG_SIGNER_WORKDIR` | `.signer` | CLI work directory |
| `TG_ACCOUNT` | `my_account` | Current account name |
| `TG_SESSION_STRING` | `...` | String session value |
| `TG_SIGNER_GUI_AUTHCODE` | `...` | GUI auth code |
| `SERVER_CHAN_SEND_KEY` | `...` | ServerChan push key |

### Logging

| Variable | Default / Example | Description |
|---|---|---|
| `PYROGRAM_LOG_ON` | `0` | Enable Pyrogram logging |

## Custom Data Directory

You can set the data directory in two ways:

1. Panel: `System Settings -> Global Settings -> Data Directory`
2. Environment variable: `APP_DATA_DIR=/your/path`

Recommendations:

- Restart the service after changing it
- The target directory must be writable
- Mount it as a persistent volume in production

## Acknowledgements

This repository is cloned, refactored, and extended from the following projects. Thanks to the original authors and maintainers:

- [TG-SignPulse](https://github.com/akasls/TG-SignPulse.git)
- [tg-signer](https://github.com/amchii/tg-signer.git)
