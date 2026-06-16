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

## Step 4: Verify setup & Initialize database table

运行 `init_setup.py` 验证配置并初始化数据库表：

```bash
{baseDir}/.venv/bin/python {baseDir}/init_setup.py
```

如果上述命令成功输出 `✓ Database connection successful!`，则代表该 Skill 的运行环境与底层数据表全部就绪。

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

- **客户直达模式**：用户直接提供链接时，无需注册到数据库，直接抓取，文件保存到 NAS
- **断点续传**：数据库已存在的资源自动跳过，不重复下载
- **双轨克隆**：视频（.mp4）和音频（.mp3）同步下载
- **ASR 简体转录**：Whisper 语音识别 + OpenCC 繁体转简体，100% 纯简体入库
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