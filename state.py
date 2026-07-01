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
    """加载缓存，返回 {category_id: {db_ctime, db_utime, nfo_mtime}}"""
    with _lock:
        if not os.path.isfile(_STATE_FILE):
            return {}
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.warning("状态缓存加载失败，将重置: %s", e)
            return {}


def save(state: dict):
    """保存缓存到文件（线程安全）"""
    with _lock:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


def is_unchanged(category_id: str, db_ctime: int, db_utime: int,
                  nfo_path: str | None, cache: dict) -> bool:
    """
    判断该记录自上次同步以来是否未发生变化。
    条件：
      - DB ctime+utime 与缓存一致（DB 侧无变化）
      - NFO 不存在 + 上次也没有 → 跳过
        或 NFO 文件 mtime 与缓存一致（NFO 侧无变化）
    """
    entry = cache.get(category_id)
    if entry is None:
        return False
    if entry.get("db_ctime") != db_ctime or entry.get("db_utime") != db_utime:
        return False
    prev_nfo_mtime = entry.get("nfo_mtime")
    if nfo_path is None:
        return prev_nfo_mtime is None
    try:
        cur_mtime = int(os.path.getmtime(nfo_path))
    except OSError:
        cur_mtime = 0
    return cur_mtime == prev_nfo_mtime


def update_cache(category_id: str, db_ctime: int, db_utime: int,
                  nfo_path: str | None, cache: dict):
    """同步完成后更新缓存"""
    nfo_mtime = None
    if nfo_path:
        try:
            nfo_mtime = int(os.path.getmtime(nfo_path))
        except OSError:
            nfo_mtime = 0
    cache[category_id] = {
        "db_ctime": db_ctime,
        "db_utime": db_utime,
        "nfo_mtime": nfo_mtime,
    }
