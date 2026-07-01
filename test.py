#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL 数据库工具 - 模块化版本
功能：
  1. 获取所有表的结构（列名、类型、可空、默认值）
  2. 查询指定表的数据（前N行）
  3. 统计 ug_video_info 表中 use_nfo 字段的取值分布
"""

import subprocess
import sys
import importlib.util
import time
from datetime import datetime, timedelta
print("DEBUG: datetime imported successfully")

# ==================== 自动安装依赖 ====================
def install_package(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True
    except subprocess.CalledProcessError:
        print(f"❌ 无法安装 {package}，请手动安装。")
        return False

def ensure_psycopg2():
    if importlib.util.find_spec("psycopg2") is not None:
        return True
    print("⚠️ 正在安装 psycopg2-binary ...")
    return install_package("psycopg2-binary")

def ensure_tabulate():
    if importlib.util.find_spec("tabulate") is not None:
        return True
    print("⚠️ 正在安装 tabulate ...")
    return install_package("tabulate")

if not ensure_psycopg2() or not ensure_tabulate():
    sys.exit(1)

import psycopg2
from psycopg2 import OperationalError
from tabulate import tabulate

# ==================== 数据库连接配置 ====================
CONFIG = {
    "host": "127.0.0.1",
    "port": 5433,
    "database": "video",
    "user": "postgres",
    "password": "",   # 无密码（trust 认证）
}

# ==================== 1. 表结构相关函数 ====================
def get_all_tables(conn):
    """获取 public 模式下所有表名"""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """)
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    return tables

def get_table_columns(conn, table_name):
    """获取指定表的所有列信息（列名、类型、可空、默认值）"""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position;
    """, (table_name,))
    columns = cur.fetchall()
    cur.close()
    return [
        {
            "Column": col[0],
            "Type": col[1],
            "Nullable": col[2],
            "Default": col[3] if col[3] is not None else ""
        }
        for col in columns
    ]

def print_table_schema(table_name, columns):
    """美观打印单张表的结构"""
    print(f"\n📋 表: {table_name}")
    print("=" * 80)
    table_data = [
        [col["Column"], col["Type"], col["Nullable"], col["Default"]]
        for col in columns
    ]
    headers = ["列名", "数据类型", "可空", "默认值"]
    print(tabulate(table_data, headers=headers, tablefmt="pipe"))
    print("=" * 80)

def print_all_schemas(conn):
    """打印所有表的结构"""
    tables = get_all_tables(conn)
    print(f"发现 {len(tables)} 个表。\n")
    for table in tables:
        cols = get_table_columns(conn, table)
        print_table_schema(table, cols)
    print("\n✅ 所有表结构已输出。")

# ==================== 2. 表数据查询相关函数 ====================
def query_table_data(conn, table_name, limit=10):
    """
    查询指定表的前 limit 行数据（返回列名和行数据）
    返回: (headers, rows) 或 (None, None) 若表不存在
    """
    cur = conn.cursor()
    try:
        # 先检查表是否存在
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
            );
        """, (table_name,))
        exists = cur.fetchone()[0]
        if not exists:
            print(f"❌ 表 '{table_name}' 不存在。")
            cur.close()
            return None, None

        # 获取列名
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position;
        """, (table_name,))
        headers = [row[0] for row in cur.fetchall()]

        # 查询数据（限制行数）
        cur.execute(f"SELECT * FROM {table_name} LIMIT %s;", (limit,))
        rows = cur.fetchall()
        cur.close()
        return headers, rows
    except Exception as e:
        print(f"❌ 查询表 '{table_name}' 失败: {e}")
        cur.close()
        return None, None

def print_table_data(table_name, headers, rows, limit=10):
    """美观打印查询到的表数据"""
    if not headers or not rows:
        print(f"📭 表 '{table_name}' 无数据或查询失败。")
        return
    print(f"\n📊 表: {table_name} (前 {len(rows)} 行)")
    print("=" * 80)
    print(tabulate(rows, headers=headers, tablefmt="pipe"))
    print("=" * 80)

# ==================== 3. 新增：统计 use_nfo 分布 ====================
def get_use_nfo_stats(conn):
    """
    统计 ug_video_info 表中 use_nfo 字段的取值分布
    返回：列表，每个元素为 (use_nfo_value, count)
    """
    cur = conn.cursor()
    # cur.execute("SELECT * FROM file_info where file_path LIKE '%.strm' LIMIT 5")
    cur.execute("SELECT * FROM ug_video_info where name LIKE '%倚天屠龙记之魔教教主%' LIMIT 5")

    stats = cur.fetchall()
    cur.close()
    return stats

def query_actor_avatars(conn, limit=10):
    cur = conn.cursor()
    # 确保 limit 是整数，防止 SQL 注入（虽然 LIMIT 中风险小）
    limit = int(limit)
    cur.execute(f"SELECT ug_actor_id, name, avatar_url, tmdb_id FROM ug_actor WHERE avatar_url ='' AND tmdb_id >0 ORDER BY ug_actor_id LIMIT {limit};")
    rows = cur.fetchall()
    cur.close()
    return rows

def print_use_nfo_stats(stats):
    """美观打印 use_nfo 统计结果"""
    if not stats:
        print("📭 ug_video_info 表无数据。")
        return
    print("\n📊 ug_video_info 表中 use_nfo 取值分布")
    print("=" * 50)
    headers = ["use_nfo 值", "记录数"]
    print(tabulate(stats, headers=headers, tablefmt="pipe"))
    print("=" * 50)
    total = sum(row[1] for row in stats)
    print(f"总计: {total} 条记录")

# ==================== 4. 主函数 ====================
def main():
    print(f"🔍 连接数据库: {CONFIG['host']}:{CONFIG['port']}/{CONFIG['database']}")
    try:
        conn = psycopg2.connect(**CONFIG)
        print("✅ 连接成功！\n")

        # cols = get_table_columns(conn, 'play_history')
        # print_table_schema('play_history', cols)
        # cols2 = get_table_columns(conn, 'favorites')
        # print_table_schema('favorites', cols2)
        # cols3 = get_table_columns(conn, 'ug_video_actor_relation')
        # print_table_schema('ug_video_actor_relation', cols3)
        # ---------- 示例：统计 use_nfo 分布 ----------
        stats = get_use_nfo_stats(conn)
        print_use_nfo_stats(stats)
        avatars = query_actor_avatars(conn, 20)
        # print("\n📸 演员头像路径:")
        # if avatars:
        #     headers = ["ID", "姓名", "头像路径", "TMDB ID"]
        #     print(tabulate(avatars, headers=headers, tablefmt="grid"))
        # else:
        #     print("没有找到非 http 开头的头像路径。")

        conn.close()
        print("\n✅ 全部任务完成。")

    except OperationalError as e:
        print(f"❌ 连接失败: {e}")

if __name__ == "__main__":
    main()