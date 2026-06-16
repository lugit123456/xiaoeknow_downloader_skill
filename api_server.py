from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import os

from init_setup import init_xiaoetong_tables
from xe_crawler import run_download_task

app = FastAPI(title="Xiaoeknow Self-Driven Pipeline API")

class CrawlerRequest(BaseModel):
    target_url: str
    direct_mode: bool = True  # 默认启用客户直达模式：直接抓取，不查表

@app.on_event("startup")
def startup_event():
    """服务启动时，全自动校验 PostgreSQL 数据表环境"""
    print("=======================================================")
    print("🚀 [系统初始化] 正在校验 PostgreSQL 数据库环境...")
    try:
        init_xiaoetong_tables()
        print("✅ [系统初始化] 数据库表结构校验成功！")
        print("💡 提示：后台 Cookie 的 6 小时常驻保活线程已由底层引擎随进程自动拉起。")
        print("=======================================================")
    except Exception as e:
        print(f"❌ [系统初始化] 数据库初始化失败，请检查数据库连接配置。错误详情: {e}")

@app.post("/download")
def run_crawler_pipeline(req: CrawlerRequest):
    """
    大模型/Agent 平台触发的统一入口

    - direct_mode=True（默认）：客户直达模式，直接抓取用户提供的 URL，
      不查询/更新数据库中的 xiaoetong_crawl_targets 表。
    - direct_mode=False：从数据库积压任务队列中领用任务，支持断点续传。
    """
    try:
        result = run_download_task(req.target_url, direct_mode=req.direct_mode)
        return result
    except Exception as e:
        return {"status": "error", "msg": f"调度服务发生未捕获异常: {str(e)}"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)