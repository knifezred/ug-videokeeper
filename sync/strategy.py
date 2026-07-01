"""同步策略 — 两种决策路径：cache 不存在 + cache 存在"""
from models import NfoRecord, SyncResult


def decide_first_sync(nfo: NfoRecord | None, db_ctime: int) -> SyncResult:
    """
    cache 不存在时的首次决策。

    规则:
      1. 无 NFO → "db_to_nfo"  (规则 1)
      2. NFO 无 <ugreen> → "db_to_nfo"  (规则 2)
      3. NFO.ugreen.ctime < DB.ctime → "nfo_to_db"  (本地更老=重新刮削过)
      4. 其他 → "db_to_nfo"  (NFO ctime >= DB ctime，用 DB 建立基线)
    """
    result = SyncResult()

    if nfo is None:
        result.direction = "db_to_nfo"
        result.scene = "1"
        result.message = "本地无 NFO，从数据库创建"
        return result

    if not nfo.has_ugreen:
        result.direction = "db_to_nfo"
        result.scene = "2"
        result.message = "NFO 无 <ugreen>，从数据库覆盖"
        return result

    if nfo.ugreen.ctime < db_ctime:
        result.direction = "nfo_to_db"
        result.scene = "3"
        result.message = (
            f"NFO ctime({nfo.ugreen.ctime}) < DB ctime({db_ctime})，"
            f"从 NFO 回写数据库"
        )
        return result

    result.direction = "db_to_nfo"
    result.scene = "4"
    result.message = "首次同步，从数据库建立 NFO 基线"
    return result


def decide_from_cache(db_ctime: int, db_utime: int,
                       cache_ctime: int, cache_utime: int) -> SyncResult:
    """
    cache 存在时的决策（不读 NFO，仅对比 DB 与缓存）。

    规则:
      cache.1: DB.ctime > cache.ctime → "nfo_to_db"  (重新刮削)
      cache.2: ctime 一致、DB.utime > cache.utime → "db_to_nfo"  (用户编辑)
      cache.3: 时间一致 → "skip"
    """
    result = SyncResult()

    if db_ctime > cache_ctime:
        result.direction = "nfo_to_db"
        result.scene = "cache.1"
        result.message = (
            f"DB 被重新刮削 (db_ctime={db_ctime} > cache_ctime={cache_ctime})，"
            f"从 NFO 回写数据库"
        )
        return result

    if db_ctime == cache_ctime and db_utime > cache_utime:
        result.direction = "db_to_nfo"
        result.scene = "cache.2"
        result.message = (
            f"用户编辑了数据 (db_utime={db_utime} > cache_utime={cache_utime})，"
            f"覆盖 NFO"
        )
        return result

    result.direction = "skip"
    result.scene = "cache.3"
    result.message = "DB ctime/utime 与缓存一致，跳过"
    return result
