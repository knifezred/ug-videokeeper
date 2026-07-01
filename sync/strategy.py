"""同步策略 — 基于 ctime/utime 的决策规则"""
from models import NfoRecord, DbRecord, SyncResult


def decide(nfo: NfoRecord, db: DbRecord) -> SyncResult:
    """
    根据 NFO 和 DB 数据决定同步方向。

    前置条件：DB 中存在此 category_id 的记录。
    (DB 无记录时由调用方直接判为 NFO→DB)

    规则:
      1.  DB 有数据、本地无 NFO → "db_to_nfo" (调用方处理，不在此函数)
      2.  NFO 存在、无 <ugreen> → "db_to_nfo"
      3.  NFO 存在、有 <ugreen>:
        3.1 ctime 一致、DB.utime > NFO.utime → "db_to_nfo" (用户编辑)
        3.2 DB.ctime > NFO.ctime → "nfo_to_db" (重新刮削)
        3.3 ctime 一致、utime 一致 → "skip" (无变化)
    """
    result = SyncResult(nfo_path=nfo.nfo_path)

    # 规则 2：NFO 无 <ugreen> → DB 覆盖 NFO
    if not nfo.has_ugreen:
        result.direction = "db_to_nfo"
        result.scene = "2"
        result.message = "NFO 无 <ugreen> 节点，从数据库覆盖"
        return result

    # 规则 3：有 <ugreen>，按 ctime/utime 决策
    nfo_ctime = nfo.ugreen.ctime
    nfo_utime = nfo.ugreen.utime
    db_ctime = db.ctime
    db_utime = db.utime

    # 3.2 DB.ctime != NFO.ctime → 谁新谁赢
    if db_ctime > nfo_ctime:
        result.direction = "nfo_to_db"
        result.scene = "3.2"
        result.message = (
            f"DB 被重新刮削 (db_ctime={db_ctime} > nfo_ctime={nfo_ctime})，"
            f"从 NFO 回写数据库"
        )
        return result
    if db_ctime < nfo_ctime:
        result.direction = "nfo_to_db"
        result.scene = "3.2"
        result.message = (
            f"NFO 比 DB 更新 (nfo_ctime={nfo_ctime} > db_ctime={db_ctime})，"
            f"从 NFO 回写数据库"
        )
        return result

    # 3.1 ctime 一致、DB.utime > NFO.utime → 用户编辑
    if db_ctime == nfo_ctime and db_utime > nfo_utime:
        result.direction = "db_to_nfo"
        result.scene = "3.1"
        result.message = (
            f"用户编辑了数据 (db_utime={db_utime} > nfo_utime={nfo_utime})，"
            f"覆盖 NFO"
        )
        return result

    # NFO.utime > DB.utime → 手动编辑了 NFO 文件
    if db_ctime == nfo_ctime and nfo_utime > db_utime:
        result.direction = "nfo_to_db"
        result.scene = "3.1b"
        result.message = (
            f"NFO 被手动编辑 (nfo_utime={nfo_utime} > db_utime={db_utime})，"
            f"回写数据库"
        )
        return result

    # 3.3 ctime 一致、utime 一致 → 跳过
    result.direction = "skip"
    result.scene = "3.3"
    result.message = "ctime 和 utime 均一致，无需同步"
    return result
