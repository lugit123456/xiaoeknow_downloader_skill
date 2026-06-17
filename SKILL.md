---
name: xiaoeknow-downloader
description: 小鹅通课程抓取技能。接收课程链接，自动下载视频/音频并做 ASR 语音转录（繁体转简体），支持断点续传和 6 小时心跳保活。
metadata:
  openclaw:
    requires:
      bins: ["python3", "ffmpeg"]
---

# 小鹅通课程抓取 Skill

当用户表达以下意图时使用此 skill：
- "帮我抓取小鹅通课程"
- "下载这个视频"
- "把课程转成文字"
- "把这个链接的文件抓取到本地"
- "爬取这个小鹅通课程"

## 触发条件

用户提供了小鹅通课程链接（格式：`https://xxx.h5.xiaoeknow.com/...`）

## 执行步骤

### 1. 调用抓取接口

向 `http://127.0.0.1:8000/download` 发送 POST 请求：

```json
{
  "target_url": "用户提供的小鹅通课程链接",
  "direct_mode": true
}
```

> `direct_mode=true`（默认，客户直达模式）：**会自动在 `xiaoetong_crawl_targets` 建档**并把抓取数据写入 `xiaoetong_crawled_data`，支持断点续传（同一 URL 再跑会跳过已存在资源）。
>
> `direct_mode=false`：从 `xiaoetong_crawl_targets` 队列中领用任务；CLI 启动时会**自动按 `id ASC` 顺序消费整个待抓取队列**，逐条处理直到 `is_fully_crawled=TRUE`。

### 2. 解析返回结果

返回 JSON 格式：

```json
{
  "status": "success",
  "course_name": "课程名称",
  "msg": "",
  "stats": {
    "total": 10,
    "downloaded": ["第1节", "第2节"],
    "skipped": ["第3节"],
    "failed": []
  }
}
```

### 3. 向用户汇报

用自然语言向用户汇报抓取结果，强调：
- 视频和音频已同步下载到 NAS
- 文本已 100% 转换为纯简体中文入库
- 新增 N 条 / 跳过 M 条 / 失败 K 条已在 stats 中体现
- 后台已开启 6 小时心跳保活机制
- 若 `last_crawl_status=empty`（课程目录为空）或 `failed`（鉴权失败 / 网络错误），会写入 `xiaoetong_crawl_targets.failure_reason` 列，可在 psql 中查询

## 工作模式

| 模式 | direct_mode | 说明 |
|------|-------------|------|
| 客户直达 | `true` | 用户直接提供链接，自动建档入库（target_url 唯一），支持断点续传 |
| 断点续传 | `false` | 从数据库积压任务队列领用，已下载的自动跳过；CLI 启动会自动消费整个待抓取队列 |

## 注意事项

- 视频/音频保存到 `XIAOE_DOWNLOAD_DIR` 配置的 NAS 路径
- 转录文本使用 Whisper ASR + OpenCC 繁简转换，100% 纯简体入库
- 首次使用需要用户扫码登录（会自动弹窗提示），Cookie 落地在 skill 目录下的 `xe_cookies.json`，删除该文件即强制重登
- **登录判断采用多信号策略**（任一满足即视为登录成功，无需依赖单一 cookie 名）：
  1. Cookie 名称命中（`uid` / `user_token` / `openid` / `p_token` / `token` 等）
  2. 页面 URL 跳离小鹅通登录中心回到 `h5.xiaoeknow.com` 目标域
  3. `localStorage` / `sessionStorage` 中存在 `token` / `userToken` / `p_token` 等键
- 智能入库门：视频（.mp4）或音频（.mp3）**任一**下载成功即写入 `xiaoetong_crawled_data`，ASR 优先用音频加速转录
- 课程目录为空（API 返回空 list）时，`last_crawl_status` 标为 `empty`，不会伪装成 `success`
- 6 小时心跳保活：首次登录成功后，后续无需重复扫码
- 文件名中的特殊字符会自动清理

## 故障排查

| 现象 | 排查方法 |
|------|---------|
| 扫码后停 5 分钟超时 | 看控制台 30 秒一次的 `[调试] 轮询 #Ns cookies=[...] url=...`，把真实 cookie 名加到 `xe_crawler.py` 的 `real_auth_names` 元组 |
| 第二次跑同一 URL 没新增数据 | 日志出现 `⏭️ 数据库已存在 resource_id=... 跳过` 表示断点续传正常，符合预期 |
| `last_crawl_status=empty` | 课程目录 API 返回空 list，可能课程未公开或鉴权失效；查 `failure_reason` 列 |