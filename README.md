# 小鹅通课程抓取助手

集成了 **Playwright** 自动授权、**FFmpeg** 媒体流处理、**PostgreSQL** 数据状态管理、**faster-whisper** 本地语音识别以及 **OpenCC** 繁简转换引擎。

支持视频/音频双介质同时克隆；转录文本 100% 强制转换为纯简体中文；后台配备 **6 小时常驻心跳保活线程**，一次登录无限续航。

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python | 3.8+ |
| PostgreSQL | 必须提前安装并运行 |
| FFmpeg | 必须配置在系统环境变量中（用于合成 `.m3u8` 流视频） |
| NAS 存储 | 用于存放下载的视频/音频文件（需配置绝对路径） |

## 项目结构

```
xiaoeknow_downloader_skill/
├── xe_crawler.py          # 核心抓取引擎（交互式 CLI 入口，含登录/抓取/入库/ASR/保活）
├── api_server.py          # FastAPI 服务端（API 入口）
├── init_setup.py          # 数据库初始化脚本
├── manifest.json          # OpenAPI 规范（用于 Agent 平台接入）
├── requirements.txt       # Python 依赖
├── SKILL.md               # Skill 说明文档
├── SKILL_SETUP.md         # 环境配置指南
├── .env.example           # 环境变量模板
└── README.md              # 本文档
```

## 安装与配置

### 1. 创建虚拟环境

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

### 2. 配置环境变量

创建 `.env` 文件：

```bash
# PostgreSQL 数据库配置
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=hub_user
POSTGRES_PASSWORD=hub_password
POSTGRES_DB=financial_hub

# NAS 文件存储路径（必填，使用绝对路径）
XIAOE_DOWNLOAD_DIR=/Volumes/nas/xiaoeknow_data/downloads
COOKIE_FILE=./xe_cookies.json
```

### 3. 初始化数据库

```bash
.venv/bin/python init_setup.py
```

### 4. 首次登录

首次运行前需要扫码登录授权：

```bash
.venv/bin/python xe_crawler.py
# 按提示在弹出的浏览器中完成扫码登录
```

## 启动服务

### API 服务（推荐用于 Agent 平台接入）

```bash
.venv/bin/python api_server.py
```

服务监听 `http://127.0.0.1:8000`，等待 Agent/大模型平台调用。

### 交互式 CLI

```bash
.venv/bin/python xe_crawler.py
```

直接运行。启动时会**自动从 `xiaoetong_crawl_targets` 队列中按 `id ASC` 顺序拉取所有 `is_enabled=TRUE AND is_fully_crawled=FALSE` 的待抓取任务**，逐条处理直到队列空。然后进入 `while True` 交互模式，用户可直接输入新链接。

## API 接口说明

### POST /download

启动小鹅通抓取任务。

**请求体：**

```json
{
  "target_url": "https://xxx.h5.xiaoeknow.com/...",
  "direct_mode": true
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_url | string | ✅ | 小鹅通课程链接 |
| direct_mode | boolean | ❌ | `true`（默认）：客户直达模式，直接抓取不查表；`false`：从数据库积压任务领用，支持断点续传 |

**响应示例：**

```json
{
  "status": "success",
  "course_name": "课程名称",
  "msg": "",
  "stats": {
    "total": 10,
    "downloaded": ["第1节", "第2节", "第3节"],
    "skipped": ["第4节", "第5节"],
    "failed": []
  }
}
```

## 核心特性

| 特性 | 说明 |
|------|------|
| 客户直达模式 | 用户直接提供链接，**自动建档入库**（写入 `xiaoetong_crawl_targets` + `xiaoetong_crawled_data`），支持断点续传 |
| CLI 自驱消费队列 | `xe_crawler.py` 启动后按 `id ASC` 顺序消费整个待抓取队列 |
| 断点续传 | 数据库已存在的资源（`resource_id` 命中）自动跳过，日志打印 `⏭️ 数据库已存在 resource_id=... 跳过（断点续传）` |
| 三信号登录检测 | Cookie 名 / URL 跳离登录页 / localStorage token，任一命中即视为登录成功，扫码后秒级续跑 |
| 智能入库门 | 视频（.mp4）或音频（.mp3）任一成功即入库；ASR 优先用音频（更快） |
| 空目录识别 | 课程目录 API 返回空 list 时 `last_crawl_status` 标 `empty`，不伪装成 `success` |
| 双轨克隆 | 视频（.mp4）和音频（.mp3）同步下载 |
| ASR 简体转录 | Whisper 语音识别 + OpenCC 繁体转简体，100% 纯简体入库 |
| 6 小时心跳保活 | 一次登录，无限续航，自动续命 Cookie |
| 文件名清理 | 自动清理特殊字符，确保文件可正常存储 |
| Cookie 自动锚定 | `COOKIE_FILE` 填相对路径时自动锚定到 skill 目录，跨进程跑也不会找不到 |

## 数据库表说明

### xiaoetong_crawl_targets（抓取目标表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| target_url | TEXT | 课程链接 |
| app_id | VARCHAR(50) | 小鹅通应用 ID |
| course_id | VARCHAR(50) | 课程 ID |
| course_name | VARCHAR(255) | 课程名称 |
| is_enabled | BOOLEAN | 是否启用 |
| crawl_frequency | INT | 抓取频率 |
| last_crawl_time | TIMESTAMP | 最后抓取时间 |
| last_crawl_status | VARCHAR(50) | 最后抓取状态。枚举值：`init`（建档）/ `running`（执行中）/ `success`（成功）/ `empty`（课程目录为空）/ `failed`（失败，详见 `failure_reason`） |
| crawled_count | INT | 已抓取数量 |
| is_fully_crawled | BOOLEAN | 是否已全量抓取 |
| failure_reason | TEXT | 失败原因（如 `empty` 状态时为"未获取到任何课程目录节点"；鉴权失败时为接口返回的 msg） |
| remarks | TEXT | 备注 |
| created_at | TIMESTAMP | 创建时间 |

### xiaoetong_crawled_data（抓取数据表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| target_id | INT | 关联目标 ID |
| resource_id | VARCHAR(50) | 资源 ID |
| resource_title | VARCHAR(255) | 资源标题 |
| video_path | TEXT | 视频本地路径 |
| audio_path | TEXT | 音频本地路径 |
| transcription_text | TEXT | 转录文本（纯简体） |
| created_at | TIMESTAMP | 创建时间 |

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| "Cookie 无效或已过期" | 删除 skill 目录下的 `xe_cookies.json` 后运行 `xe_crawler.py`，按提示重新扫码登录 |
| 扫码后停 5 分钟不自动续跑 | 看控制台 30 秒一次的 `[调试] 轮询 #Ns cookies=[...] url=...` 日志，把小鹅通实际种下的真实 cookie 名加到 `xe_crawler.py` 的 `real_auth_names` 元组里 |
| 第二次跑同一 URL 没新增数据 | 日志出现 `⏭️ 数据库已存在 resource_id=... 跳过（断点续传）` 表示符合预期，断点续传不会重复入库 |
| `last_crawl_status=empty` | 课程目录 API 返回空 list，可能课程未公开或鉴权失效；查同行的 `failure_reason` 列 |
| "NAS 目录不可用" | 检查 `XIAOE_DOWNLOAD_DIR` 路径是否正确配置；不可写时会自动 fallback 到 `<skill_dir>/xiaoe_downloads` |
| "数据库连接失败" | 检查 PostgreSQL 是否运行，确认 `.env` 中 `POSTGRES_*` 变量配置正确 |
| "FFmpeg 异常" | 确认 ffmpeg 已安装并配置到系统环境变量（`which ffmpeg`） |