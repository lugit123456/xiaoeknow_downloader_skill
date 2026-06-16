"""
小鹅通爬虫数据库初始化脚本
用于在 PostgreSQL (financial_hub) 数据库中创建表
"""
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_DIR, ".env"))


def get_db_connection():
    """建立数据库连接"""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        dbname=os.getenv("POSTGRES_DB"),
    )


def init_xiaoetong_tables():
    """创建小鹅通爬虫数据表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 抓取目标表
    create_targets_table = """
    CREATE TABLE IF NOT EXISTS xiaoetong_crawl_targets (
        id SERIAL PRIMARY KEY,
        target_url TEXT UNIQUE,
        app_id VARCHAR(50),
        course_id VARCHAR(50),
        course_name VARCHAR(255),
        is_enabled BOOLEAN DEFAULT TRUE,
        crawl_frequency INT DEFAULT 0,
        last_crawl_time TIMESTAMP WITH TIME ZONE,
        last_crawl_status VARCHAR(50),
        crawled_count INT DEFAULT 0,
        is_fully_crawled BOOLEAN DEFAULT FALSE,
        failure_reason TEXT,
        remarks TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
    create_targets_index = """
    CREATE INDEX IF NOT EXISTS idx_xiaoetong_targets_status ON xiaoetong_crawl_targets(last_crawl_status);
    CREATE INDEX IF NOT EXISTS idx_xiaoetong_targets_enabled ON xiaoetong_crawl_targets(is_enabled);
    """

    # 2. 抓取数据表
    create_data_table = """
    CREATE TABLE IF NOT EXISTS xiaoetong_crawled_data (
        id SERIAL PRIMARY KEY,
        target_id INT REFERENCES xiaoetong_crawl_targets(id),
        resource_id VARCHAR(50) UNIQUE,
        resource_title VARCHAR(255),
        video_path TEXT,
        audio_path TEXT,
        transcription_text TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
    create_data_index = """
    CREATE INDEX IF NOT EXISTS idx_xiaoetong_crawled_target ON xiaoetong_crawled_data(target_id);
    CREATE INDEX IF NOT EXISTS idx_xiaoetong_crawled_resource ON xiaoetong_crawled_data(resource_id);
    """

    try:
        cursor.execute(create_targets_table)
        for idx_sql in create_targets_index.split(";"):
            idx_sql = idx_sql.strip()
            if idx_sql:
                cursor.execute(idx_sql)

        cursor.execute(create_data_table)
        for idx_sql in create_data_index.split(";"):
            idx_sql = idx_sql.strip()
            if idx_sql:
                cursor.execute(idx_sql)

        conn.commit()
        print("✓ Database connection successful!")
        print("✓ Table [xiaoetong_crawl_targets] initialized successfully.")
        print("✓ Table [xiaoetong_crawled_data] initialized successfully.")
        return True

    except Exception as e:
        print(f"✗ Database error: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    success = init_xiaoetong_tables()
    sys.exit(0 if success else 1)