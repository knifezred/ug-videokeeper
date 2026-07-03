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
    processed_dirs: set[tuple] = set()
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
                log.debug("跳过不存在的目录: %s", folder)
                continue

            dir_key = _dir_key(folder, fr.season_num, fr.file_name)
            if dir_key in processed_dirs:
                log.debug("跳过已处理目录: %s (key=%s)", folder, dir_key)
                continue
            processed_dirs.add(dir_key)

            # 电视剧：统一用 ugreen_tv.nfo 处理
            if fr.video_type == 2:
                tv_nfo_path = os.path.join(folder, "ugreen_tv.nfo")
                _process_tv(conn, fr, folder, tv_nfo_path, cache, results, stats)
                continue

            cached_entry = cache.get(fr.category_id)

            log.debug("处理: cat=%s name=%s folder=%s cache=%s",
                      fr.category_id, fr.video_name, folder,
                      "hit" if cached_entry else "miss")

            # ===== 路径 A: cache 存在 → 纯 DB vs cache 比较 =====
            if cached_entry is not None:
                decision = decide_from_cache(
                    fr.video_ctime, fr.video_utime,
                    cached_entry.get("db_ctime", 0),
                    cached_entry.get("db_utime", 0),
                    db_vid=fr.ug_video_info_id,
                    cache_vid=cached_entry.get("db_vid", 0),
                )
                if decision.direction == "skip":
                    stats["cached"] += 1
                    log.debug("  → %s %s", decision.scene, decision.message)
                    continue

                log.info("  → %s %s", decision.scene, decision.message)
                # cache.1 或 cache.2 → 执行同步
                nfo_path = _find_nfo_for_record(fr)
                result = _exec_cached(conn, fr, folder, nfo_path, decision)
                results.append(result)
                stats[result.direction] = stats.get(result.direction, 0) + 1
                log.info("  → 结果: direction=%s scene=%s", result.direction, result.scene)

                st.update_cache(fr.category_id, fr.video_ctime, fr.video_utime,
                                cache, db_vid=fr.ug_video_info_id)
                continue

            # ===== 路径 B: cache 不存在 → 读 NFO 首次决策 =====
            nfo_path = _find_nfo_for_record(fr)
            nfo = read_nfo(nfo_path) if nfo_path else None

            decision = decide_first_sync(nfo, fr.video_ctime)
            log.info("  → %s %s", decision.scene, decision.message)
            result = _exec_first_sync(conn, fr, folder, nfo, nfo_path, decision)
            results.append(result)
            stats[result.direction] = stats.get(result.direction, 0) + 1
            log.info("  → 结果: direction=%s scene=%s synced=%s path=%s",
                     result.direction, result.scene, result.synced, result.nfo_path)

            if result.synced:
                st.update_cache(fr.category_id, fr.video_ctime, fr.video_utime,
                                cache, db_vid=fr.ug_video_info_id)

        if not DRY_RUN:
            conn.commit()
            st.save(cache)
            log.info("DB 已提交，缓存已保存 (%d 条)", len(cache))
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
            log.warning("cache.1: 需 NFO→DB 但本地无 NFO, cat=%s folder=%s",
                        fr.category_id, folder)
            return SyncResult(nfo_path="", direction="error", scene="cache.1",
                              message="需 NFO→DB 但本地无 NFO")
        nfo = read_nfo(nfo_path)
        if nfo is None:
            log.warning("cache.1: NFO 解析失败 %s", nfo_path)
            return SyncResult(nfo_path=nfo_path, direction="error", scene="cache.1",
                              message="NFO 解析失败")
        log.debug("cache.1: 执行 NFO→DB, nfo=%s actors=%d play_history=%d",
                  nfo_path, len(nfo.official.actors), len(nfo.ugreen.play_history))
        queries.sync_nfo_to_db(conn, nfo)
        log.info("cache.1: NFO→DB 完成, cat=%s", fr.category_id)
        return decision

    # cache.2: 用户编辑 → DB→NFO
    if nfo_path is None:
        log.debug("cache.2: NFO 不存在，从 DB 创建, cat=%s folder=%s",
                  fr.category_id, folder)
        _create_nfo_from_db(conn, fr, folder)
        return decision

    nfo = read_nfo(nfo_path)
    if nfo is None:
        log.warning("cache.2: NFO 解析失败 %s", nfo_path)
        return SyncResult(nfo_path=nfo_path, direction="error", scene="cache.2",
                          message="NFO 解析失败")
    db_rec = queries.fetch_video_by_category(conn, fr.category_id)
    if db_rec is None:
        log.warning("cache.2: DB 无此记录, cat=%s", fr.category_id)
        return SyncResult(nfo_path=nfo_path, direction="error", scene="cache.2",
                          message="DB 无此记录")
    log.debug("cache.2: 执行 DB→NFO, cat=%s name=%s", fr.category_id, db_rec.name)
    _db_to_nfo(conn, nfo, db_rec)
    log.info("cache.2: DB→NFO 完成 → %s", nfo_path)
    return decision


def _exec_first_sync(conn, fr: FileRecord, folder: str, nfo: NfoRecord | None,
                     nfo_path: str | None, decision: SyncResult) -> SyncResult:
    """cache 不存在时的首次同步执行"""
    decision.nfo_path = nfo_path or os.path.join(folder, "movie.nfo")

    if decision.scene == "1":  # 无 NFO → 创建
        log.debug("scene=1: 从 DB 创建 NFO, cat=%s folder=%s type=%s",
                  fr.category_id, folder,
                  "episode" if fr.season_num > 0 else ("tvshow" if fr.video_type == 2 else "movie"))
        _create_nfo_from_db(conn, fr, folder)
        return decision

    if decision.scene == "2":  # 无 ugreen → DB→NFO
        db_rec = queries.fetch_video_by_category(conn, fr.category_id)
        if db_rec:
            log.debug("scene=2: DB→NFO, cat=%s name=%s", fr.category_id, db_rec.name)
            _db_to_nfo(conn, nfo, db_rec)
        else:
            log.warning("首次同步 scene=2 但 DB 无记录: category_id=%s folder=%s",
                        fr.category_id, folder)
            decision.synced = False
        return decision

    if decision.scene == "3":  # NFO ctime < DB ctime → NFO→DB
        log.debug("scene=3: NFO→DB, cat=%s nfo=%s actors=%d",
                  nfo.ugreen.category_id if nfo else "?", nfo_path,
                  len(nfo.official.actors) if nfo else 0)
        queries.sync_nfo_to_db(conn, nfo)
        return decision

    # scene == "4": DB→NFO 建立基线
    db_rec = queries.fetch_video_by_category(conn, fr.category_id)
    if db_rec:
        log.debug("scene=4: DB→NFO 基线, cat=%s name=%s", fr.category_id, db_rec.name)
        _db_to_nfo(conn, nfo, db_rec)
    else:
        log.warning("scene=4: DB 无记录, 回退 NFO→DB, cat=%s", fr.category_id)
        queries.sync_nfo_to_db(conn, nfo)
    return decision


def _create_nfo_from_db(conn, fr: FileRecord, folder: str):
    """创建 NFO 文件。若目录已有 NFO 则复用；否则按类型决定文件名。"""
    existing = find_nfo_in_dir(folder)
    if existing:
        nfo_path = existing
        # 从已有 NFO 读取 type，读不到默认 movie
        existing_nfo = read_nfo(existing)
        nfo_type = existing_nfo.nfo_type if existing_nfo else "movie"
        log.debug("复用已有 NFO: %s (type=%s)", nfo_path, nfo_type)
    else:
        nfo_type, nfo_path = "movie", os.path.join(folder, "movie.nfo")
        log.debug("创建新 NFO: type=%s path=%s cat=%s", nfo_type, nfo_path, fr.category_id)

    nfo = NfoRecord(
        nfo_type=nfo_type, nfo_path=nfo_path, video_dir=folder,
        official=VideoMeta(),
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
        log.debug("DB 无记录，写入空 NFO 骨架: %s", nfo_path)
        write_nfo(nfo)
        return
    log.debug("DB→NFO 写入: %s (name=%s)", nfo_path, db_rec.name)
    _db_to_nfo(conn, nfo, db_rec)


def _ensure_season_nfo(conn, fr: FileRecord, folder: str):
    pass  # 已废弃，由 _process_tv 统一处理



def _process_tv(conn, fr: FileRecord, folder: str, nfo_path: str,
                cache: dict, results: list, stats: dict):
    """电视剧：读取/创建 ugreen_tv.nfo，cache 决策 + 同步"""
    from nfo.reader import read_tv_nfo
    from nfo.writer import write_tv_nfo

    cached_entry = cache.get(fr.category_id)

    if cached_entry is not None:
        decision = decide_from_cache(
            fr.video_ctime, fr.video_utime,
            cached_entry.get("db_ctime", 0),
            cached_entry.get("db_utime", 0),
            db_vid=fr.ug_video_info_id,
            cache_vid=cached_entry.get("db_vid", 0),
        )
        if decision.direction == "skip":
            stats["cached"] += 1
            log.debug("  → %s %s", decision.scene, decision.message)
            return

        log.info("  → %s %s (TV)", decision.scene, decision.message)
        if decision.scene == "cache.1":
            season = read_tv_nfo(nfo_path)
            if season:
                queries.sync_tv_nfo_to_db(conn, season, folder)
                stats["nfo_to_db"] = stats.get("nfo_to_db", 0) + 1
            else:
                stats["error"] = stats.get("error", 0) + 1
        else:
            season = queries.build_tv_season_from_db(conn, fr.category_id, folder)
            if season:
                write_tv_nfo(season, nfo_path)
                stats["db_to_nfo"] = stats.get("db_to_nfo", 0) + 1
        st.update_cache(fr.category_id, fr.video_ctime, fr.video_utime, cache,
                        db_vid=fr.ug_video_info_id)
        return

    # cache 不存在 → 首次同步
    season = read_tv_nfo(nfo_path)
    if season:
        log.info("  → 首次同步 TV: ugreen_tv.nfo 已存在")
        queries.sync_tv_nfo_to_db(conn, season, folder)
        stats["nfo_to_db"] = stats.get("nfo_to_db", 0) + 1
    else:
        log.info("  → 首次同步 TV: 从 DB 生成 ugreen_tv.nfo")
        season = queries.build_tv_season_from_db(conn, fr.category_id, folder)
        if season:
            write_tv_nfo(season, nfo_path)
            stats["db_to_nfo"] = stats.get("db_to_nfo", 0) + 1
    st.update_cache(fr.category_id, fr.video_ctime, fr.video_utime, cache,
                    db_vid=fr.ug_video_info_id)


def _db_to_nfo(conn, nfo: NfoRecord, db_record):
    cat = db_record.category_id or nfo.ugreen.category_id
    log.debug("DB→NFO: 查询关联数据 cat=%s", cat)
    db_actors = queries.fetch_actors(conn, cat)
    db_play = queries.fetch_play_history(conn, cat)
    db_fav = queries.fetch_favorites(conn, cat)
    db_col = queries.fetch_collection(conn, cat)
    # 补全 ugreen.category_id（NFO 可能无 <ugreen>）
    if not nfo.ugreen.category_id:
        nfo.ugreen.category_id = db_record.category_id
    log.debug("DB→NFO: actors=%d play=%d fav=%d col=%s", len(db_actors),
              len(db_play), len(db_fav), db_col["name"] if db_col else "无")
    write_nfo_from_db(nfo, db_record, db_actors, db_play, db_fav, db_col)


def _dir_key(folder: str, season: int, file_name: str = "") -> tuple:
    if season and file_name:
        return (folder, season, file_name)
    return (folder, season) if season else (folder,)


def _find_nfo_for_record(fr: FileRecord) -> str | None:
    """查找 FileRecord 对应的 NFO 文件，按类型优先级匹配。

    电影 (video_type=1): movie.nfo → {文件名}.nfo → 目录下任一 .nfo
    电视剧 (video_type=2): ugreen_tv.nfo → 目录下任一 .nfo
    """
    folder = fr.folder_path
    file_nfo = os.path.splitext(fr.file_name)[0] + ".nfo"

    if fr.video_type == 1:
        candidates = ["movie.nfo", file_nfo]
    elif fr.video_type == 2:
        candidates = ["ugreen_tv.nfo"]
    else:
        candidates = [file_nfo, "season.nfo", "tvshow.nfo"]

    for name in candidates:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            log.debug("查找 NFO: 匹配 %s (type=%d season=%d)", name, fr.video_type, fr.season_num)
            return path

    # 兜底：目录下任一 .nfo（可能是不在上述候选列表中的命名）
    any_nfo = find_nfo_in_dir(folder)
    log.debug("查找 NFO: 兜底匹配 %s", any_nfo or "(无)")
    return any_nfo


def _log_summary(stats: dict, total: int):
    log.info("======== 同步汇总 ========")
    log.info("  缓存跳过: %d", stats.get("cached", 0))
    log.info("  NFO → DB: %d", stats.get("nfo_to_db", 0))
    log.info("  DB → NFO: %d", stats.get("db_to_nfo", 0))
    log.info("  跳过:     %d", stats.get("skip", 0))
    if stats.get("error", 0):
        log.warning("  错误:     %d", stats.get("error", 0))
    log.info("  总计:     %d", total)
    if stats.get("error", 0):
        log.warning("======== %d 条错误，请检查上方日志 ========", stats["error"])
    else:
        log.info("======== 同步完成，无错误 ========")
