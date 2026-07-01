"""同步执行器 — 遍历 file_info 表，cache 不存在/存在两种决策路径"""
import os
from config import log, DRY_RUN, TARGET_PATH
from db import queries
from db.connection import connect
from nfo.reader import read_nfo, find_nfo_in_dir
from nfo.writer import write_nfo, write_nfo_from_db
from sync.strategy import decide_first_sync, decide_from_cache
from models import NfoRecord, VideoMeta, UgreenMeta, SyncResult, FileRecord
import state as st


def run_sync() -> list[SyncResult]:
    conn = connect()
    results: list[SyncResult] = []
    processed_dirs: set[str] = set()
    stats = {"nfo_to_db": 0, "db_to_nfo": 0, "skip": 0, "error": 0, "cached": 0}

    cache = st.load()
    log.info("状态缓存已加载: %d 条", len(cache))

    try:
        file_records = queries.fetch_all_file_info(conn, TARGET_PATH)
        log.info("file_info 共 %d 条记录" + (" (路径过滤: %s)" if TARGET_PATH else ""),
                 len(file_records), *([TARGET_PATH] if TARGET_PATH else []))

        for fr in file_records:
            folder = fr.folder_path
            if not folder or not os.path.isdir(folder):
                continue

            dir_key = _dir_key(folder, fr.season_num)
            if dir_key in processed_dirs:
                continue
            processed_dirs.add(dir_key)

            cached_entry = cache.get(fr.category_id)

            # ===== 路径 A: cache 存在 → 纯 DB vs cache 比较 =====
            if cached_entry is not None:
                decision = decide_from_cache(
                    fr.video_ctime, fr.video_utime,
                    cached_entry.get("db_ctime", 0),
                    cached_entry.get("db_utime", 0),
                )
                if decision.direction == "skip":
                    stats["cached"] += 1
                    continue

                # cache.1 或 cache.2 → 执行同步
                nfo_path = find_nfo_in_dir(folder)
                result = _exec_cached(conn, fr, folder, nfo_path, decision)
                results.append(result)
                stats[result.direction] = stats.get(result.direction, 0) + 1

                updated_nfo = find_nfo_in_dir(folder)
                st.update_cache(fr.category_id, fr.video_ctime, fr.video_utime,
                                updated_nfo, cache)
                continue

            # ===== 路径 B: cache 不存在 → 读 NFO 首次决策 =====
            nfo_path = find_nfo_in_dir(folder)
            nfo = read_nfo(nfo_path) if nfo_path else None

            decision = decide_first_sync(nfo, fr.video_ctime)
            result = _exec_first_sync(conn, fr, folder, nfo, nfo_path, decision)
            results.append(result)
            stats[result.direction] = stats.get(result.direction, 0) + 1

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


def _exec_cached(conn, fr: FileRecord, folder: str, nfo_path: str | None,
                 decision: SyncResult) -> SyncResult:
    """cache 存在时的同步执行：cache.1 = NFO→DB / cache.2 = DB→NFO"""
    decision.nfo_path = nfo_path or ""

    if decision.scene == "cache.1":  # 重新刮削 → NFO→DB
        if nfo_path is None:
            return SyncResult(nfo_path="", direction="error", scene="cache.1",
                              message="需 NFO→DB 但本地无 NFO")
        nfo = read_nfo(nfo_path)
        if nfo is None:
            return SyncResult(nfo_path=nfo_path, direction="error", scene="cache.1",
                              message="NFO 解析失败")
        queries.sync_nfo_to_db(conn, nfo)
        return decision

    # cache.2: 用户编辑 → DB→NFO
    if nfo_path is None:
        _create_nfo_from_db(conn, fr, folder)
        decision.nfo_path = os.path.join(folder, "movie.nfo")
        return decision

    nfo = read_nfo(nfo_path)
    if nfo is None:
        return SyncResult(nfo_path=nfo_path, direction="error", scene="cache.2",
                          message="NFO 解析失败")
    db_rec = queries.fetch_video_by_category(conn, fr.category_id)
    if db_rec is None:
        return SyncResult(nfo_path=nfo_path, direction="error", scene="cache.2",
                          message="DB 无此记录")
    _db_to_nfo(conn, nfo, db_rec)
    return decision


def _exec_first_sync(conn, fr: FileRecord, folder: str, nfo: NfoRecord | None,
                     nfo_path: str | None, decision: SyncResult) -> SyncResult:
    """cache 不存在时的首次同步执行"""
    decision.nfo_path = nfo_path or os.path.join(folder, "movie.nfo")

    if decision.scene == "1":  # 无 NFO → 创建
        _create_nfo_from_db(conn, fr, folder)
        return decision

    if decision.scene == "2":  # 无 ugreen → DB→NFO
        db_rec = queries.fetch_video_by_category(conn, fr.category_id)
        if db_rec:
            _db_to_nfo(conn, nfo, db_rec)
        return decision

    if decision.scene == "3":  # NFO ctime < DB ctime → NFO→DB
        queries.sync_nfo_to_db(conn, nfo)
        return decision

    # scene == "4": DB→NFO 建立基线
    db_rec = queries.fetch_video_by_category(conn, fr.category_id)
    if db_rec:
        _db_to_nfo(conn, nfo, db_rec)
    else:
        queries.sync_nfo_to_db(conn, nfo)
    return decision


def _create_nfo_from_db(conn, fr: FileRecord, folder: str):
    """创建 NFO 文件"""
    nfo_type, nfo_path = "movie", os.path.join(folder, "movie.nfo")
    if fr.video_type == 1:
        if fr.season_num > 0:
            nfo_type, nfo_path = "episode", os.path.join(folder, "season.nfo")
        else:
            nfo_type, nfo_path = "tvshow", os.path.join(folder, "tvshow.nfo")

    nfo = NfoRecord(
        nfo_type=nfo_type, nfo_path=nfo_path, video_dir=folder,
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
