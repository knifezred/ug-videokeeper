"""同步执行器 — 遍历 file_info 表，以 folder_path 定位 NFO + 状态缓存跳过"""
import os
from config import log, DRY_RUN
from db import queries
from db.connection import connect
from nfo.reader import read_nfo, find_nfo_in_dir
from nfo.writer import write_nfo, write_nfo_from_db
from sync.strategy import decide
from models import NfoRecord, VideoMeta, UgreenMeta, SyncResult, FileRecord
import state as st


def run_sync() -> list[SyncResult]:
    """遍历 file_info 表，对每个视频目录执行同步决策"""
    conn = connect()
    results: list[SyncResult] = []
    processed_dirs: set[str] = set()
    stats = {"nfo_to_db": 0, "db_to_nfo": 0, "skip": 0, "error": 0, "cached": 0}

    cache = st.load()
    log.info("状态缓存已加载: %d 条", len(cache))

    try:
        file_records = queries.fetch_all_file_info(conn)
        log.info("file_info 共 %d 条记录", len(file_records))

        for fr in file_records:
            folder = fr.folder_path
            if not folder or not os.path.isdir(folder):
                continue

            dir_key = _dir_key(folder, fr.season_num)
            if dir_key in processed_dirs:
                continue
            processed_dirs.add(dir_key)

            nfo_path = find_nfo_in_dir(folder)

            # ---- 快速跳过：缓存匹配 ----
            if st.is_unchanged(fr.category_id, fr.video_ctime, fr.video_utime,
                               nfo_path, cache):
                stats["cached"] += 1
                continue

            # ---- 有变化，执行同步 ----
            result = _process_one(conn, fr, folder, nfo_path)
            results.append(result)
            stats[result.direction] = stats.get(result.direction, 0) + 1

            # 同步后重新检测 NFO（可能被创建或覆盖了）
            updated_nfo = find_nfo_in_dir(folder)
            st.update_cache(fr.category_id, fr.video_ctime, fr.video_utime,
                            updated_nfo, cache)

        if not DRY_RUN:
            st.save(cache)
            conn.commit()
        else:
            conn.rollback()
            log.info("[DRY RUN] 跳过写入，缓存未保存")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _log_summary(stats, len(results))
    return results


def _process_one(conn, fr: FileRecord, folder: str,
                 nfo_path: str | None) -> SyncResult:
    """处理单条 file_info 记录"""

    # 规则 1: DB 有数据、本地无 NFO → 创建
    if nfo_path is None:
        result = SyncResult(
            nfo_path=os.path.join(folder, "movie.nfo"),
            direction="db_to_nfo", scene="1",
            message=f"本地无 NFO，从数据库创建: {fr.video_name or folder}",
        )
        _create_nfo_from_db(conn, fr, folder)
        return result

    # 读取本地 NFO
    nfo = read_nfo(nfo_path)
    if nfo is None:
        return SyncResult(
            nfo_path=nfo_path, direction="error", scene="-",
            message="NFO 解析失败",
        )

    db_rec = queries.fetch_video_by_category(conn, fr.category_id)
    if db_rec is None:
        result = SyncResult(
            nfo_path=nfo_path, direction="nfo_to_db", scene="1",
            message="DB 无此记录，从 NFO 回写",
        )
        queries.sync_nfo_to_db(conn, nfo)
        return result

    decision = decide(nfo, db_rec)

    if decision.direction == "nfo_to_db":
        queries.sync_nfo_to_db(conn, nfo)
    elif decision.direction == "db_to_nfo":
        _db_to_nfo(conn, nfo, db_rec)

    return decision


def _create_nfo_from_db(conn, fr: FileRecord, folder: str):
    """规则 1: 从数据库数据创建 NFO 文件"""
    nfo_type = "movie"
    nfo_path = os.path.join(folder, "movie.nfo")
    if fr.video_type == 1:
        if fr.season_num > 0:
            nfo_type = "episode"
            nfo_path = os.path.join(folder, "season.nfo")
        else:
            nfo_type = "tvshow"
            nfo_path = os.path.join(folder, "tvshow.nfo")

    nfo = NfoRecord(
        nfo_type=nfo_type,
        nfo_path=nfo_path,
        video_dir=folder,
        ugreen=UgreenMeta(
            category_id=fr.category_id,
            ug_video_info_id=fr.ug_video_info_id,
            media_lib_set_id=fr.media_lib_set_id,
            ctime=fr.video_ctime,
            utime=fr.video_utime,
        ),
    )

    db_rec = queries.fetch_video_by_category(conn, fr.category_id)
    if db_rec is None:
        write_nfo(nfo)
        return

    db_actors = queries.fetch_actors(conn, fr.category_id)
    db_play = queries.fetch_play_history(conn, fr.category_id)
    db_fav = queries.fetch_favorites(conn, fr.category_id)
    db_col = queries.fetch_collection(conn, fr.category_id)
    write_nfo_from_db(nfo, db_rec, db_actors, db_play, db_fav, db_col)


def _db_to_nfo(conn, nfo: NfoRecord, db_record):
    """DB → NFO 覆盖"""
    db_actors = queries.fetch_actors(conn, nfo.ugreen.category_id)
    db_play = queries.fetch_play_history(conn, nfo.ugreen.category_id)
    db_fav = queries.fetch_favorites(conn, nfo.ugreen.category_id)
    db_col = queries.fetch_collection(conn, nfo.ugreen.category_id)
    write_nfo_from_db(nfo, db_record, db_actors, db_play, db_fav, db_col)


def _dir_key(folder: str, season: int) -> str:
    return f"{folder}###{season}" if season else folder


def _log_summary(stats: dict, total: int):
    log.info("======== 同步汇总 ========")
    log.info("  缓存跳过: %d", stats.get("cached", 0))
    log.info("  NFO → DB: %d", stats.get("nfo_to_db", 0))
    log.info("  DB → NFO: %d", stats.get("db_to_nfo", 0))
    log.info("  跳过:     %d", stats.get("skip", 0))
    if stats.get("error", 0):
        log.info("  错误:     %d", stats.get("error", 0))
    log.info("  总计:     %d", total)
