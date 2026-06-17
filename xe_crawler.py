import os
import json
import re
import time
import random
import urllib.parse
import subprocess
import requests
from datetime import datetime
import threading
import psycopg2
from psycopg2.extras import DictCursor
from faster_whisper import WhisperModel
from playwright.sync_api import sync_playwright
from opencc import OpenCC
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 全局配置
# ==========================================
_cookie_file_raw = os.getenv("COOKIE_FILE", "xe_cookies.json")
COOKIE_FILE = _cookie_file_raw if os.path.isabs(_cookie_file_raw) else os.path.join(os.path.dirname(__file__), _cookie_file_raw)

# NAS 文件存储路径（支持绝对路径）
_xiaoe_download_dir = os.getenv("XIAOE_DOWNLOAD_DIR", "/Volumes/nas/xiaoeknow_data/downloads")
if not os.path.isabs(_xiaoe_download_dir):
    _xiaoe_download_dir = os.path.join(os.path.dirname(__file__), _xiaoe_download_dir)

BASE_DOWNLOAD_DIR = _xiaoe_download_dir

# 如果 NAS 目录不可用，fallback 到本地目录
if not os.path.exists(os.path.dirname(BASE_DOWNLOAD_DIR)) or not os.access(os.path.dirname(BASE_DOWNLOAD_DIR), os.W_OK):
    print(f"[警告] NAS 目录不可用: {os.path.dirname(BASE_DOWNLOAD_DIR)}")
    BASE_DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "xiaoe_downloads")
    print(f"[警告] 使用本地 fallback 目录: {BASE_DOWNLOAD_DIR}")

# 数据库配置
DB_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB', 'financial_hub'),
    'user': os.getenv('POSTGRES_USER', 'hub_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'hub_password'),
    'host': os.getenv('POSTGRES_HOST', '127.0.0.1'),
    'port': os.getenv('POSTGRES_PORT', '5432')
}

# 初始化繁体转简体工具 ('t2s' 代表 Traditional to Simplified)
cc = OpenCC('t2s')

# ==========================================
# 核心引擎：ASR 语音识别模块
# ==========================================
_asr_model = None


def get_asr_model():
    """单例模式加载 Whisper 模型"""
    global _asr_model
    if _asr_model is None:
        print("\n⚙️ 正在加载 Whisper 模型 (初次运行会自动下载权重)...")
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        _asr_model = WhisperModel("small", device="cpu", compute_type="int8")
        print("✅ 模型加载完毕！")
    return _asr_model


def transcribe_audio(filepath):
    """将音视频文件转录为文本，并强制转换为简体字"""
    model = get_asr_model()
    print(f"🎙️ 正在进行语音识别转文本: {os.path.basename(filepath)}")
    segments, _ = model.transcribe(filepath, beam_size=5, language="zh")

    full_text = ""
    for segment in segments:
        full_text += segment.text + " "

    simplified_text = cc.convert(full_text.strip())
    return simplified_text


from init_setup import init_xiaoetong_tables, get_db_connection, upsert_target_by_url


# ==========================================
# 底层工具库：爬虫与下载
# ==========================================
def get_app_and_course(url):
    match = re.search(r'https://([^.]+)\.h5\.xiaoeknow\.com.*?/course/ecourse/([^/?]+)', url)
    if match:
        return match.group(1), match.group(2)
    raise ValueError("无法解析链接。")


def login_and_save_cookies(url):
    print("\n[系统提示] 需验证身份，请在弹出的浏览器中扫码/账号登录...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)

        # 自动检测登录完成：采用多信号策略
        #   1) Cookie 名称匹配真正的登录关键字
        #   2) 页面 URL 跳离小鹅通登录中心
        #   3) localStorage / sessionStorage 中存在 token
        # 任一满足即视为登录成功
        initial_url = page.url
        print(f"[系统提示] 等待扫码登录（5 分钟超时），初始 URL: {initial_url}")

        # 真正的登录 Cookie 名称关键字（不能是 anony_token）
        real_auth_names = ('uid', 'user_token', 'openid', 'unionid', 'session_token',
                          'phone', 'email', 'user_id', 'token_type',
                          'p_token', 'xet_token', 'xiaoeknow_token', 'token')

        for i in range(300):
            time.sleep(1)
            current = context.cookies()
            current_url = page.url

            # 信号 1：Cookie 名称命中
            real_auth = any(
                any(k in c.get('name', '').lower() for k in real_auth_names)
                and 'anony' not in c.get('name', '').lower()
                for c in current
            )

            # 信号 2：URL 跳离登录页（跳到 h5.xiaoeknow.com 目标域，且不再是登录中心）
            url_left_login = (
                'h5.xiaoeknow.com' in current_url.lower()
                and 'passport' not in current_url.lower()
                and 'login' not in current_url.lower()
                and current_url != initial_url
            )

            # 信号 3：localStorage / sessionStorage 中存在常见 token 字段
            storage_auth = False
            try:
                storage_auth = page.evaluate("""
                    () => {
                        const keys = ['token','userToken','user_token','access_token',
                                      'p_token','uid','xet_token','xiaoeknow_token'];
                        for (const store of [localStorage, sessionStorage]) {
                            try {
                                for (const k of keys) {
                                    const v = store.getItem(k);
                                    if (v && v.length > 4) return true;
                                }
                            } catch(e) {}
                        }
                        return false;
                    }
                """)
            except Exception:
                # localStorage 不可用时（如跨域 iframe 内）静默忽略
                pass

            # 每 30 秒打印一次调试快照，方便排查
            if i % 30 == 0:
                cookie_names = [c.get('name', '') for c in current]
                print(f"[调试] 轮询 #{i}s cookies={cookie_names} url={current_url}")

            if real_auth or url_left_login or storage_auth:
                reasons = []
                if real_auth:   reasons.append("cookie匹配")
                if url_left_login: reasons.append("URL跳离登录页")
                if storage_auth: reasons.append("localStorage有token")
                print(f"[系统提示] 登录成功（{ ' / '.join(reasons) }），继续。")
                break
        else:
            print("❌ [系统提示] 登录超时（5 分钟未检测到登录态）。")
            browser.close()
            raise TimeoutError("登录超时：请在 5 分钟内完成扫码")

        cookies = context.cookies()
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cookies, f)
        browser.close()
        return cookies


def load_cookies():
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def extract_user_id(cookies):
    for c in cookies:
        if 'sa_jssdk' in c['name']:
            try:
                data = json.loads(urllib.parse.unquote(c['value']))
                if 'distinct_id' in data:
                    return data['distinct_id']
            except:
                continue
    for c in cookies:
        match = re.search(r'(u_[a-z0-9]+_[a-zA-Z0-9]+)', c['value'])
        if match:
            return match.group(1)
    raise ValueError("无法提取 user_id。")


def safe_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def download_file(url, filepath):
    if os.path.exists(filepath):
        return "skipped"
    try:
        response = requests.get(url, stream=True)
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return "downloaded"
    except Exception as e:
        print(f"下载异常: {e}")
        return "failed"


def download_m3u8(m3u8_url, filepath):
    if os.path.exists(filepath):
        return "skipped"
    command = ['ffmpeg', '-y', '-i', m3u8_url, '-c', 'copy', '-bsf:a', 'aac_adtstoasc', filepath]
    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
        return "downloaded"
    except Exception as e:
        print(f"FFmpeg异常: {e}")
        return "failed"


# ==========================================
# 定时心跳维持机制
# ==========================================
def ping_xiaoe_server():
    cookies_list = load_cookies()
    if not cookies_list:
        return False

    app_id = None
    for cookie in cookies_list:
        if 'xiaoeknow.com' in cookie.get('domain', ''):
            match = re.search(r'([^.]+)\.h5\.xiaoeknow\.com', cookie['domain'])
            if match:
                app_id = match.group(1)
                break

    if not app_id:
        return False

    session = requests.Session()
    for cookie in cookies_list:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

    session.headers.update({
        'origin': f'https://{app_id}.h5.xiaoeknow.com',
        'user-agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36',
        'content-type': 'application/x-www-form-urlencoded'
    })

    ping_url = f"https://{app_id}.h5.xiaoeknow.com/xe.course.business_go.e_course.last_learn_resource.get/1.0.0"
    try:
        res = session.post(ping_url, data={'bizData[app_id]': app_id}, timeout=10)
        res_json = res.json()
        if res_json.get('code') != 401:
            print(f"\n[❤️ 保活守护] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 心跳延续成功，Cookie 状态健康。")
            return True
        else:
            print("\n[⚠️ 保活守护] 服务器返回未登录或已失效，请在下一次输入指令时重新登录。")
            return False
    except:
        return False


def keepalive_background_worker():
    time.sleep(15)
    while True:
        ping_xiaoe_server()
        time.sleep(6 * 60 * 60)


# ==========================================
# 核心任务流程
# ==========================================
def run_download_task(target_url, target_id=None, direct_mode=False):
    """
    核心下载引擎，整合 DB 管理与 ASR 解析

    参数:
        target_url: 小鹅通课程链接
        target_id: 数据库中的任务 ID（可选）
        direct_mode: 客户直达模式。如果为 True，则直接抓取用户提供的链接，
                     不查询/更新数据库中的 xiaoetong_crawl_targets 表。
                     适用于用户直接提供链接的场景。
    """
    try:
        app_id, course_id = get_app_and_course(target_url)
    except ValueError:
        return {"status": "error", "msg": "链接格式似乎不对，请提供正确的小鹅通课程链接。"}

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    target_record = None
    db_target_id = None

    # ============================================
    # 【统一入口】始终 upsert 一条 target 记录
    # direct_mode 路径下也复用/新建 target，使每条抓取都可入库
    # ============================================
    if target_id:
        cur.execute("SELECT * FROM xiaoetong_crawl_targets WHERE id = %s", (target_id,))
        target_record = cur.fetchone()
    else:
        target_record = upsert_target_by_url(cur, target_url, app_id, course_id)

    if target_record:
        if not target_record['is_enabled']:
            cur.close()
            conn.close()
            return {"status": "error", "msg": "该目标任务在数据库中已被停用。"}
        if target_record['is_fully_crawled'] and not direct_mode:
            cur.close()
            conn.close()
            return {"status": "success", "course_name": target_record['course_name'],
                    "msg": "✅ 目标已处于全量抓取完毕状态，无需重复执行。"}
        db_target_id = target_record['id']
    else:
        cur.execute('''
            INSERT INTO xiaoetong_crawl_targets (target_url, app_id, course_id, last_crawl_status)
            VALUES (%s, %s, %s, 'init') RETURNING id
        ''', (target_url, app_id, course_id))
        db_target_id = cur.fetchone()[0]
        conn.commit()
        cur.execute("SELECT * FROM xiaoetong_crawl_targets WHERE id = %s", (db_target_id,))
        target_record = cur.fetchone()

    cur.execute("UPDATE xiaoetong_crawl_targets SET last_crawl_time = %s, last_crawl_status = 'running' WHERE id = %s",
                (datetime.now(), db_target_id))
    conn.commit()

    if direct_mode:
        print(f"\n[客户直达模式] 已自动建档 (target_id={db_target_id})，抓取结果将入库。")

    # 2. 网络交互与鉴权
    cookies_list = load_cookies()

    # 检查 Cookie 是否有效，无效则弹窗登录
    cookie_valid = False
    if cookies_list:
        # 简单验证：检查 Cookie 是否包含必要的域名
        for c in cookies_list:
            if 'xiaoeknow.com' in c.get('domain', ''):
                cookie_valid = True
                break

    if not cookie_valid:
        print("\n[系统提示] Cookie 无效或已过期，正在唤起浏览器登录...")
        cookies_list = login_and_save_cookies(target_url)

    try:
        user_id = extract_user_id(cookies_list)
    except ValueError as e:
        cur.execute("UPDATE xiaoetong_crawl_targets SET last_crawl_status = 'failed', failure_reason = %s WHERE id = %s",
                    (str(e), db_target_id))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "error", "msg": str(e)}

    session = requests.Session()
    for cookie in cookies_list:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
    session.headers.update({
        'origin': f'https://{app_id}.h5.xiaoeknow.com',
        'user-agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36'
    })

    # 3. 课程基本信息提取
    session.headers.update({'content-type': 'application/x-www-form-urlencoded'})
    try:
        info_res = session.post(f"https://{app_id}.h5.xiaoeknow.com/xe.course.business_go.core.info.get/2.0.0",
                                data={'bizData[resource_id]': course_id}, timeout=15)
        if not info_res.text or info_res.text.strip() == "":
            cur.close()
            conn.close()
            return {"status": "error", "msg": "服务器返回空响应，请检查网络或重新登录"}
        info_res = info_res.json()
    except requests.exceptions.RequestException as e:
        cur.close()
        conn.close()
        return {"status": "error", "msg": f"网络请求失败: {str(e)}"}
    except Exception as e:
        cur.close()
        conn.close()
        return {"status": "error", "msg": f"课程信息解析失败: {str(e)}"}

    # 检查是否登录过期
    if info_res.get('code') == 401 or (info_res.get('data') is None and info_res.get('msg')):
        print("\n[系统提示] 登录已过期，正在唤起浏览器重新登录...")
        cookies_list = login_and_save_cookies(target_url)

        # 重建 session
        session = requests.Session()
        for cookie in cookies_list:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
        session.headers.update({
            'origin': f'https://{app_id}.h5.xiaoeknow.com',
            'user-agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36'
        })
        session.headers.update({'content-type': 'application/x-www-form-urlencoded'})

        try:
            info_res = session.post(f"https://{app_id}.h5.xiaoeknow.com/xe.course.business_go.core.info.get/2.0.0",
                                    data={'bizData[resource_id]': course_id}, timeout=15)
            if not info_res.text or info_res.text.strip() == "":
                cur.close()
                conn.close()
                return {"status": "error", "msg": "重新登录后服务器仍返回空响应"}
            info_res = info_res.json()
        except Exception as e:
            cur.close()
            conn.close()
            return {"status": "error", "msg": f"重新登录后课程信息获取仍然失败: {str(e)}"}

    if info_res.get('code') != 0 and info_res.get('code') != 200:
        cur.close()
        conn.close()
        return {"status": "error", "msg": f"课程信息获取异常: {info_res.get('msg', '未知错误')}"}

    course_name = safe_filename(info_res.get('data', {}).get('resource_name', "未命名课程_" + course_id))

    cur.execute("UPDATE xiaoetong_crawl_targets SET course_name = %s WHERE id = %s", (course_name, db_target_id))
    conn.commit()

    # 确保下载目录存在
    course_dir = os.path.join(BASE_DOWNLOAD_DIR, course_name)
    if not os.path.exists(course_dir):
        os.makedirs(course_dir, exist_ok=True)

    res1 = session.post(
        f"https://{app_id}.h5.xiaoeknow.com/xe.course.business_go.e_course.last_learn_resource.get/1.0.0",
        data={'bizData[course_id]': course_id, 'bizData[app_id]': app_id}).json()
    first_resource_id = res1.get('data', {}).get('resource_id')

    payload_catalog = {
        'bizData[app_id]': app_id, 'bizData[resource_id]': first_resource_id,
        'bizData[course_id]': course_id, 'bizData[p_id]': 0, 'bizData[order]': 'asc',
        'bizData[page]': 1, 'bizData[page_size]': 50, 'bizData[is_display_auth_sections]': 0
    }
    course_list = session.post(
        f"https://{app_id}.h5.xiaoeknow.com/xe.course.business_go.avoidlogin.e_course.resource_catalog_list.get/1.0.0",
        data=payload_catalog).json().get('data', {}).get('list', [])

    stats = {"total": len(course_list), "downloaded": [], "skipped": [], "failed": []}
    print(f"\n[执行器] 开始处理《{course_name}》，共 {len(course_list)} 节内容...")

    crawled_count = (target_record['crawled_count'] or 0) if target_record else 0

    # 4. 循环解析、下载并存库
    for index, item in enumerate(course_list, start=1):
        title = safe_filename(item.get('resource_title', f'未命名_{index}'))
        r_id = item.get('resource_id')

        # 断点续传校验（所有模式都执行：direct_mode 也跳过已抓过的资源）
        cur.execute("SELECT id FROM xiaoetong_crawled_data WHERE resource_id = %s", (r_id,))
        if cur.fetchone():
            stats["skipped"].append(title)
            print(f"[{index:02d}] ⏭️ 数据库已存在 resource_id={r_id} 的记录，跳过（断点续传，不会重复入库）: {title}")
            continue

        print(f"[{index:02d}] 正在处理: {title}")
        session.headers.update({'content-type': 'application/x-www-form-urlencoded'})
        detail_res = session.post(
            f"https://{app_id}.h5.xiaoeknow.com/xe.course.business_go.video.detail_info.get/2.0.0",
            data={'bizData[resource_id]': r_id, 'bizData[product_id]': course_id,
                  'bizData[opr_sys]': 'MacIntel'}).json()

        play_sign = detail_res.get('data', {}).get('video_info', {}).get('play_sign')
        if not play_sign:
            stats["failed"].append(title)
            continue

        session.headers.update({'content-type': 'application/json'})
        play_res = session.post(f"https://{app_id}.h5.xiaoeknow.com/xe.material-center.play/getPlayUrl",
                                json={"org_app_id": app_id, "app_id": app_id, "user_id": user_id,
                                      "play_sign": [play_sign], "play_line": "A", "opr_sys": "MacIntel"}).json()

        play_data = play_res.get('data', {}).get(play_sign, {}).get('play_list', {})
        video_m3u8_url = play_data.get('720p_hls', {}).get('play_url')
        audio_mp3_url = play_data.get('mp3', {}).get('play_url')

        video_path_db = None
        audio_path_db = None
        video_status = "none"
        audio_status = "none"

        if video_m3u8_url:
            video_path_local = os.path.join(course_dir, f"{index:02d}_{title}.mp4")
            print(f"   🎬 正在下载视频流...")
            video_status = download_m3u8(video_m3u8_url, video_path_local)
            if video_status in ["downloaded", "skipped"]:
                video_path_db = video_path_local

        if audio_mp3_url:
            audio_path_local = os.path.join(course_dir, f"{index:02d}_{title}.mp3")
            print(f"   🎵 正在下载音频流...")
            audio_status = download_file(audio_mp3_url, audio_path_local)
            if audio_status in ["downloaded", "skipped"]:
                audio_path_db = audio_path_local

        # 只要任意一个介质下载成功，就允许入库
        if video_path_db or audio_path_db:
            transcript = ""
            # ASR 优先用音频（更快），其次用视频
            asr_target = audio_path_db if audio_path_db else video_path_db
            try:
                transcript = transcribe_audio(asr_target)
            except Exception as e:
                print(f"❌ 语音识别失败: {e}")

            # 写入数据库（所有模式都执行 — 修复 direct_mode=True 不入库的 bug）
            cur.execute('''
                INSERT INTO xiaoetong_crawled_data (target_id, resource_id, resource_title, video_path, audio_path, transcription_text)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (db_target_id, r_id, title, video_path_db, audio_path_db, transcript))

            crawled_count += 1
            cur.execute("UPDATE xiaoetong_crawl_targets SET crawled_count = %s WHERE id = %s", (crawled_count, db_target_id))
            conn.commit()

            stats["downloaded"].append(title)
            media = []
            if video_path_db: media.append("视频")
            if audio_path_db: media.append("音频")
            print(f"   ✅ 入库成功（{ '/'.join(media) }）: {title}")
        else:
            stats["failed"].append(title)
            print(f"   ❌ 视频和音频均未下载成功，跳过入库: {title}")

        if index < len(course_list):
            time.sleep(random.uniform(5, 10))

    # 5. 更新目标总状态（所有模式都执行）
    if stats["total"] == 0:
        # 课程目录为空：标 empty，不要伪装成 success
        cur.execute("UPDATE xiaoetong_crawl_targets SET last_crawl_status = 'empty', failure_reason = %s, is_fully_crawled = %s WHERE id = %s",
                    ("未获取到任何课程目录节点（API 返回空 list）", False, db_target_id))
    else:
        is_fully_crawled = (crawled_count >= stats["total"])
        cur.execute("UPDATE xiaoetong_crawl_targets SET last_crawl_status = 'success', is_fully_crawled = %s WHERE id = %s",
                    (is_fully_crawled, db_target_id))
    conn.commit()

    cur.close()
    conn.close()

    print(f"\n[执行器] 《{course_name}》入库完成：新增 {len(stats['downloaded'])} 条，跳过 {len(stats['skipped'])} 条，失败 {len(stats['failed'])} 条。")
    return {"status": "success", "course_name": course_name, "stats": stats, "msg": ""}


# ==========================================
# 交互层：模拟自然语言 Skill Agent
# ==========================================
def _fetch_next_pending_task():
    """从 DB 拉一条待抓取任务；队列空或异常时返回 None。"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute('''
            SELECT id, target_url, course_name
            FROM xiaoetong_crawl_targets
            WHERE is_enabled = TRUE
              AND is_fully_crawled = FALSE
              AND (last_crawl_status IS NULL OR last_crawl_status != 'running')
            ORDER BY id ASC
            LIMIT 1
        ''')
        return cur.fetchone()
    except Exception as e:
        print(f"⚠️ 检索待抓取任务异常: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def chatbot_agent():
    print("=======================================================")
    print("🤖 你的私人小鹅通下载助手已上线！(含全量存储、ASR 简体及自动后台保活)")
    print("=======================================================")

    # 优先检索数据库中未完成的待抓取任务（持续消费整个队列）
    pending_task = _fetch_next_pending_task()
    if pending_task:
        print(f"\n⚡ [自动触发] 检测到数据库中有未完成的任务，开始按队列顺序抓取。")
        print("-------------------------------------------------------")

        while pending_task:
            task_id = pending_task['id']
            task_url = pending_task['target_url']
            display_name = pending_task['course_name'] if pending_task['course_name'] else task_url
            print(f"\n📂 当前任务: {display_name} (id={task_id})")

            result = run_download_task(task_url, target_id=task_id)

            if result["status"] == "error":
                print(f"🤖 助手系统消息: 任务中止，错误原因: {result['msg']}")
                # 当前任务失败，停止整条队列避免被同一错误反复阻塞
                break
            else:
                course_name = result.get("course_name", display_name)
                stats = result.get("stats", {})
                if stats:
                    print(f"\n🎉 [自动完成] 《{course_name}》全链路处理完毕。")
                    print(
                        f"   - 📊 资源总计：{stats.get('total', 0)} 个 | ✅ 新下载/转录：{len(stats.get('downloaded', []))} 个 | ⏭️ 跳过：{len(stats.get('skipped', []))} 个\n")

            # 拉下一条
            pending_task = _fetch_next_pending_task()

    print("ℹ️ 当前数据库中已无待抓取的活跃任务（或所有任务已全量抓取完毕）。")
    print("您可以对我说：'帮我下载这个资源：https://...' 或者直接发送新链接。")
    print("输入 '退出' 结束对话。")
    print("=======================================================")

    while True:
        user_input = input("\n🧑 你: ").strip()

        if user_input.lower() in ['退出', 'exit', 'quit']:
            print("🤖 助手: 好的，下次见！")
            break

        url_match = re.search(r'(https://[a-zA-Z0-9-]+\.h5\.xiaoeknow\.com[^\s]+)', user_input)

        if not url_match:
            print("🤖 助手: 数据库中暂无待抓取队列。若需继续，请先发给我新的课程资源链接哦（以 https:// 开头）。")
            continue

        target_url = url_match.group(1)
        print("🤖 助手: 收到！正在锁定任务链接并启动抓取，这可能需要一点时间，请留意是否需要登录...")

        # 客户直达模式：直接抓取用户提供的 URL，不查表
        result = run_download_task(target_url, direct_mode=True)

        if result["status"] == "error":
            print(f"🤖 助手: 抱歉，遇到了点问题：{result['msg']}")
        elif "✅" in result.get("msg", ""):
            print(f"🤖 助手: {result['msg']}")
        else:
            course_name = result["course_name"]
            stats = result["stats"]

            reply = f"🤖 助手: 搞定啦！《{course_name}》处理完毕。\n"
            reply += f"   - 📊 列表总计发现：{stats['total']} 个资源。\n"
            reply += f"   - ✅ 本次成功下载（视音频同步）且转录：{len(stats['downloaded'])} 个。\n"
            reply += f"   - ⏭️ 数据库已存在，跳过：{len(stats['skipped'])} 个。\n"

            if stats['failed']:
                reply += f"   - ❌ 下载/提取失败：{len(stats['failed'])} 个。\n"

            print(reply)


if __name__ == "__main__":
    try:
        init_xiaoetong_tables()
    except Exception as e:
        print(f"⚠️ 数据库初始化失败，请检查 DB_CONFIG 参数配置是否正确。错误信息: {e}")
        exit(1)

    keepalive_thread = threading.Thread(target=keepalive_background_worker, daemon=True)
    keepalive_thread.start()

    chatbot_agent()