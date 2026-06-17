---
name: xiaoeknow-downloader-setup
description: 为小鹅通课程下载系统初始化虚拟环境、安装 Playwright 和 Whisper 依赖、配置 PostgreSQL 数据库并初始化数据表，文件保存到 NAS。
metadata:
  openclaw:
    requires:
      bins: ["python3", "ffmpeg"]
---

# 小鹅通课程下载系统环境配置 Skill

本 skill 完成小鹅通课程爬虫的虚拟环境创建、Python 依赖安装、Playwright 浏览器核心下载，以及规范化的 PostgreSQL 数据库建表初始化。文件（视频、音频、转录文本）保存到 NAS 存储。

**本 skill 不涉及具体的抓取逻辑，仅做环境与数据库结构的初始化。**

## When to use

在以下情况下应当执行本 skill：
- 项目首次部署或从仓库克隆后需要进行初始化。
- 项目根目录下的虚拟环境 `.venv/` 不存在。
- 项目根目录下的 `.env` 配置文件丢失。
- 自动化运行前需要确保 PostgreSQL 数据库中已创建对应的数据表。
- 其他功能 skill 报出"依赖未安装"、"未找到浏览器"或"数据库连接失败"等错误。

## Step 1: Create virtual environment

检查 `{baseDir}/.venv` 是否存在。如果不存在，则执行以下命令创建 Python 虚拟环境：

```bash
python3 -m venv {baseDir}/.venv
```

## Step 2: Install Python dependencies & Playwright Browser

激活虚拟环境，升级包管理工具并安装项目依赖，同时拉取 Playwright 所需的 Chromium 内核：

```bash
{baseDir}/.venv/bin/pip install -r {baseDir}/requirements.txt
{baseDir}/.venv/bin/playwright install chromium
```

核心依赖说明 (defined in requirements.txt):

- **playwright** — 提供自动化浏览器接管与扫码登录。
- **faster-whisper** — 本地语音识别模型（ASR 转文本）。
- **opencc-python-reimplemented** — 繁体转简体，确保纯简体入库。
- **psycopg2-binary** — 规范连接统一的投研数据库。
- **python-dotenv** — 加载项目环境变量。
- **requests** — HTTP 请求与会话管理。
- **fastapi / uvicorn** — API 服务端框架。

**注意**：必须提前安装 `ffmpeg` 并配置到系统环境变量中（用于合成 `.m3u8` 流视频）。

## Step 3: Configure environment variables

检查 `{baseDir}/.env` 是否存在。如果不存在，从模板生成：

```bash
if [ ! -f "{baseDir}/.env" ]; then
  cat > "{baseDir}/.env" << 'EOF'
# PostgreSQL 数据库配置 (金融数据中心规范)
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=hub_user
POSTGRES_PASSWORD=hub_password
POSTGRES_DB=financial_hub

# NAS 文件存储路径 (必填，使用绝对路径)
XIAOE_DOWNLOAD_DIR=/Volumes/nas/xiaoeknow_data/downloads
COOKIE_FILE=./xe_cookies.json
EOF
fi
```

统一数据库变量规范对照表：

| Variable | Description | Default |
|----------|-------------|---------|
| POSTGRES_HOST | PostgreSQL 服务器地址 | 127.0.0.1 |
| POSTGRES_PORT | PostgreSQL 服务器端口 | 5432 |
| POSTGRES_USER | 数据库用户（读写权限） | hub_user |
| POSTGRES_PASSWORD | 数据库用户密码 | hub_password |
| POSTGRES_DB | 数据库名称（所有爬虫汇聚于此） | financial_hub |
| XIAOE_DOWNLOAD_DIR | NAS 文件存储根目录 | /Volumes/nas/xiaoeknow_data/downloads |
| COOKIE_FILE | Cookie 缓存文件路径。**若填相对路径则自动锚定到 skill 目录**(避免跨进程跑时找不到文件)。删除该文件即强制重新扫码。 | ./xe_cookies.json |

## Step 4: Verify setup & Initialize database table

运行 `init_setup.py` 验证配置并初始化数据库表：

```bash
{baseDir}/.venv/bin/python {baseDir}/init_setup.py
```

如果上述命令成功输出 `✓ Database connection successful!`，则代表该 Skill 的运行环境与底层数据表全部就绪。

如需重置登录授权，删除 skill 目录下的 `xe_cookies.json` 文件后再启动 `xe_crawler.py` 即可触发重新扫码。

## 登录检测说明

`login_and_save_cookies`（位于 `xe_crawler.py`）采用**多信号策略**判断扫码登录是否成功，命中任一信号即视为登录成功并自动续跑，无需依赖单一 cookie 名：

| 信号 | 说明 |
|------|------|
| ① Cookie 名称 | 命中关键字 `uid` / `user_token` / `openid` / `unionid` / `session_token` / `phone` / `email` / `user_id` / `token_type` / `p_token` / `xet_token` / `xiaoeknow_token` / `token`,且 cookie 名不含 `anony` |
| ② URL 跳离 | 浏览器页面从 `passport.xiaoeknow.com` / 登录页跳回 `h5.xiaoeknow.com` 目标域 |
| ③ localStorage | 页面 `localStorage` / `sessionStorage` 中存在 `token` / `userToken` / `user_token` / `access_token` / `p_token` / `uid` / `xet_token` / `xiaoeknow_token` 等键(值长度 > 4) |

**排查指南**：控制台每 30 秒会打印一行 `[调试] 轮询 #Ns cookies=[...] url=...`。如果扫码后停 5 分钟超时，看这一行就能看到小鹅通实际种下的 cookie 名是什么，把它加到 `real_auth_names` 元组里即可命中信号 ①。信号 ② 和 ③ 通常 1~2 秒内就会触发，扫码后秒级续跑是正常表现。

## 使用方法

本系统有两个入口：

### 1. API 服务（推荐）

启动 FastAPI 服务，通过自然语言指挥 Agent 调用：

```bash
source .venv/bin/activate
python api_server.py
```

服务监听 `http://127.0.0.1:8000`，支持以下接口：

**POST /download**

```json
{
  "target_url": "https://xxx.h5.xiaoeknow.com/...",
  "direct_mode": true
}
```

| 参数 | 说明 |
|------|------|
| `target_url` | 小鹅通课程链接（必填） |
| `direct_mode` | 客户直达模式。`true`（默认）：用户直接提供链接，直接抓取不查表。`false`：从数据库积压任务队列领用，支持断点续传。 |

### 2. 交互式 CLI

直接运行爬虫脚本，通过命令行交互下载：

```bash
source .venv/bin/activate
python xe_crawler.py
```

### 数据库表说明

| 表名 | 说明 |
|------|------|
| `xiaoetong_crawl_targets` | 抓取目标表（URL、课程名、状态、断点页码） |
| `xiaoetong_crawled_data` | 抓取数据表（资源标题、视频路径、音频路径、转录文本） |

### 核心特性

- **客户直达模式**：用户直接提供链接时，自动在 `xiaoetong_crawl_targets` 建档并写入 `xiaoetong_crawled_data`，支持断点续传
- **CLI 自驱消费队列**：`python xe_crawler.py` 启动后自动按 `id ASC` 顺序消费所有 `is_enabled=TRUE AND is_fully_crawled=FALSE` 的待抓取任务，单条任务失败时停止整条队列（避免被同一错误反复阻塞）
- **断点续传**：数据库已存在的资源（`xiaoetong_crawled_data.resource_id` 命中）自动跳过，不重复下载；日志会打印 `⏭️ 数据库已存在 resource_id=... 跳过（断点续传）` 提示
- **双轨克隆**：视频（.mp4）和音频（.mp3）同步下载
- **智能入库门**：视频和音频任一成功即入库；ASR 优先用音频（更快），其次用视频
- **空目录识别**：课程目录 API 返回空 list 时，`last_crawl_status` 标 `empty` 并写入 `failure_reason`，不会伪装成 `success`
- **ASR 简体转录**：Whisper 语音识别 + OpenCC 繁体转简体，100% 纯简体入库
- **三信号登录检测**：Cookie 名 / URL 跳离 / localStorage token，任一命中即视为登录成功
- **6 小时心跳保活**：一次登录，无限续航，自动续命 Cookie

### .env 变量说明

| 变量名 | 是否必填 | 说明 |
|--------|---------|------|
| `POSTGRES_HOST` | ✅ 必填 | PostgreSQL 服务器地址 |
| `POSTGRES_PORT` | ✅ 必填 | PostgreSQL 服务器端口 |
| `POSTGRES_USER` | ✅ 必填 | 数据库用户 |
| `POSTGRES_PASSWORD` | ✅ 必填 | 数据库用户密码 |
| `POSTGRES_DB` | ✅ 必填 | 数据库名称 |
| `XIAOE_DOWNLOAD_DIR` | ✅ 必填 | NAS 下载根目录（绝对路径） |
| `COOKIE_FILE` | 可选 | Cookie 缓存文件路径 |