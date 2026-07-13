"""本地状态缓存 — SQLite 记录上次同步的快照，用于跳过无变化记录"""
import json
import os
import sqlite3
from config import log

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_DB_PATH = os.path.join(_DATA_DIR, "state.db")
_JSON_PATH = os.path.join(_DATA_DIR, "state.json")


def open_db() -> sqlite3.Connection:
    """打开 state.db 连接。

    统一走 WAL 模式：executor（写）与 watcher（读/写）不会互相阻塞，
    避免默认 rollback 日志下 "database is locked"。
    """
    os.makedirs(_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_cache (
        category_id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")
    return conn


def _get_conn() -> sqlite3.Connection:
    """获取线程本地 SQLite 连接（兼容旧接口）"""
    return open_db()


def load() -> dict:
    """（兼容旧接口）全量加载缓存。百万级库请改用 get_one / load_batch"""
    conn = _get_conn()
    rows = conn.execute("SELECT category_id, data FROM sync_cache").fetchall()
    conn.close()
    return {row[0]: json.loads(row[1]) for row in rows}


def save(state: dict):
    """（兼容旧接口）全量保存缓存到 SQLite"""
    conn = _get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO sync_cache (category_id, data) VALUES (?, ?)",
        [(cat, json.dumps(val, ensure_ascii=False)) for cat, val in state.items()]
    )
    conn.commit()
    conn.close()


def get_one(conn: sqlite3.Connection, category_id: str) -> dict | None:
    """单条查询缓存"""
    row = conn.execute(
        "SELECT data FROM sync_cache WHERE category_id = ?", (category_id,)
    ).fetchone()
    return json.loads(row[0]) if row else None


def load_batch(conn: sqlite3.Connection, cat_ids: list[str]) -> dict:
    """批量加载缓存，返回 {category_id: data}"""
    if not cat_ids:
        return {}
    placeholders = ",".join("?" * len(cat_ids))
    rows = conn.execute(
        f"SELECT category_id, data FROM sync_cache WHERE category_id IN ({placeholders})",
        cat_ids,
    ).fetchall()
    return {row[0]: json.loads(row[1]) for row in rows}


def save_batch(conn: sqlite3.Connection, batch: dict):
    """批量保存缓存条目"""
    if not batch:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO sync_cache (category_id, data) VALUES (?, ?)",
        [(cat, json.dumps(val, ensure_ascii=False)) for cat, val in batch.items()]
    )


def make_entry(db_ctime: int, db_utime: int, db_vid: int = 0,
               max_mtime: int = 0, content_hash: str = "",
               fav_count: int = 0, collection_id: str = "") -> dict:
    """创建缓存条目 dict，供 caller 放入 batch"""
    return {
        "db_ctime": db_ctime,
        "db_utime": db_utime,
        "db_vid": db_vid,
        "max_mtime": max_mtime,
        "content_hash": content_hash,
        "fav_count": fav_count,
        "collection_id": collection_id,
    }


def update_cache(category_id: str, db_ctime: int, db_utime: int,
                 cache: dict, db_vid: int = 0, max_mtime: int = 0,
                 content_hash: str = "", fav_count: int = 0,
                 collection_id: str = ""):
    """（兼容旧接口）同步完成后更新缓存 dict"""
    cache[category_id] = make_entry(db_ctime, db_utime, db_vid,
                                     max_mtime, content_hash, fav_count,
                                     collection_id)


def upsert_one(conn: sqlite3.Connection, category_id: str, db_ctime: int,
               db_utime: int, db_vid: int = 0, max_mtime: int = 0,
               content_hash: str = "", fav_count: int = 0,
               collection_id: str = ""):
    """单条写入/更新缓存条目（供 watcher 等单点更新使用）"""
    conn.execute(
        "INSERT OR REPLACE INTO sync_cache (category_id, data) VALUES (?, ?)",
        (category_id, json.dumps(
            make_entry(db_ctime, db_utime, db_vid, max_mtime, content_hash,
                       fav_count, collection_id),
            ensure_ascii=False)),
    )


def migrate_from_json():
    """首次运行时从 state.json 迁移到 SQLite"""
    if not os.path.isfile(_JSON_PATH):
        return
    conn = _get_conn()
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data:
            conn.executemany(
                "INSERT OR REPLACE INTO sync_cache (category_id, data) VALUES (?, ?)",
                [(cat, json.dumps(val, ensure_ascii=False)) for cat, val in data.items()]
            )
            conn.commit()
            log.info("state.json 已迁移到 SQLite: %d 条", len(data))
        os.rename(_JSON_PATH, _JSON_PATH + ".bak")
        log.info("state.json 已重命名为 state.json.bak")
    except (json.JSONDecodeError, IOError) as e:
        log.warning("state.json 迁移失败（可忽略）: %s", e)
    finally:
        conn.close()
