"""本地状态缓存 — JSON 文件记录上次同步的快照，用于跳过无变化记录"""
import json
import os
import threading
from config import log

# 缓存文件路径
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "state.json")

# 线程锁（executor + watchdog 共享）
_lock = threading.Lock()


def load() -> dict:
    """加载缓存，返回 {category_id: {db_ctime, db_utime}}"""
    with _lock:
        if not os.path.isfile(_STATE_FILE):
            log.debug("缓存文件不存在: %s", _STATE_FILE)
            return {}
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            log.debug("缓存已加载: %d 条来自 %s", len(data), _STATE_FILE)
            return data
        except (json.JSONDecodeError, IOError) as e:
            log.warning("状态缓存加载失败，将重置: %s", e)
            return {}


def save(state: dict):
    """保存缓存到文件（线程安全）"""
    with _lock:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        log.debug("缓存已保存: %d 条 → %s", len(state), _STATE_FILE)


def update_cache(category_id: str, db_ctime: int, db_utime: int,
                  cache: dict, db_vid: int = 0, max_mtime: int = 0,
                  content_hash: str = ""):
    """同步完成后更新缓存"""
    cache[category_id] = {
        "db_ctime": db_ctime,
        "db_utime": db_utime,
        "db_vid": db_vid,
        "max_mtime": max_mtime,
        "content_hash": content_hash,
    }
