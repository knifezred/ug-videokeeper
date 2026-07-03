"""同步策略 — 基于 .ugreen.json + DB cache 的两条决策路径"""
from models import SyncResult
from config import log


def decide_first_sync(json_ctime: int, db_ctime: int) -> SyncResult:
    """
    cache 不存在时的首次决策。基于 .ugreen.json 的存在与 ctime。

    first.1: json.ctime < db.ctime → NFO/JSON → DB  (重新刮削，恢复数据)
    first.2: json.ctime >= db.ctime → DB → JSON       (建立/刷新基线)
    first.3: json 不存在 → DB → JSON                   (全新建立基线)
    """
    result = SyncResult()

    if json_ctime == 0:
        # .ugreen.json 不存在 → 全新基线
        result.direction = "db_to_json"
        result.scene = "first.3"
        result.message = ".ugreen.json 不存在，从数据库建立"
        log.debug("策略决策 first.3: .ugreen.json 不存在 → DB→JSON")
        return result

    if json_ctime < db_ctime:
        result.direction = "nfo_to_db"
        result.scene = "first.1"
        result.message = (
            f".ugreen.json ctime({json_ctime}) < DB ctime({db_ctime})，"
            f"从本地恢复数据库"
        )
        log.debug("策略决策 first.1: json ctime=%d < DB ctime=%d → NFO/JSON→DB",
                  json_ctime, db_ctime)
        return result

    result.direction = "db_to_json"
    result.scene = "first.2"
    result.message = ".ugreen.json 已存在，从数据库刷新"
    log.debug("策略决策 first.2: json ctime=%d >= DB ctime=%d → DB→JSON",
              json_ctime, db_ctime)
    return result


def decide_from_cache(db_ctime: int, db_utime: int,
                       cache_ctime: int, cache_utime: int,
                       db_vid: int = 0, cache_vid: int = 0,
                       db_mtime: int = 0, cache_mtime: int = 0,
                       db_hash: str = "", cache_hash: str = "") -> SyncResult:
    """
    cache 存在时的决策。

    cache.1: DB.ctime > cache.ctime 或 vid 变化 → NFO/JSON → DB  (重新刮削)
    cache.2: 以上无变化，但 max_mtime > cache_max_mtime → DB → JSON  (用户行为)
    cache.4: 以上无变化，但 content_hash 变化 → DB → JSON  (编辑 ug_video_info)
    cache.3: 全部一致 → skip
    """
    result = SyncResult()

    if db_ctime > cache_ctime or (db_vid and cache_vid and db_vid != cache_vid):
        result.direction = "nfo_to_db"
        result.scene = "cache.1"
        cause = "db_ctime 增大" if db_ctime > cache_ctime else "vid 变化"
        result.message = (
            f"DB 被重新刮削 ({cause}: db_ctime={db_ctime})，"
            f"从 NFO/JSON 恢复数据库"
        )
        log.debug("策略决策 cache.1: %s → NFO/JSON→DB", cause)
        return result

    if db_mtime > cache_mtime:
        result.direction = "db_to_json"
        result.scene = "cache.2"
        result.message = (
            f"用户行为触发同步 (max_mtime={db_mtime} > cache_mtime={cache_mtime})，"
            f"刷新 .ugreen.json"
        )
        log.debug("策略决策 cache.2: max_mtime=%d > cache_mtime=%d → DB→JSON",
                  db_mtime, cache_mtime)
        return result

    if db_hash and cache_hash and db_hash != cache_hash:
        result.direction = "db_to_json"
        result.scene = "cache.4"
        result.message = (
            f"用户编辑了视频信息 (hash 变化: {db_hash[:8]}... → {cache_hash[:8]}...)，"
            f"刷新 .ugreen.json"
        )
        log.debug("策略决策 cache.4: hash 变化 → DB→JSON")
        return result

    result.direction = "skip"
    result.scene = "cache.3"
    result.message = "DB ctime/utime 与缓存一致，跳过"
    log.debug("策略决策 cache.3: ctime/utime 一致 → skip")
    return result
