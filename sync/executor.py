"""同步执行器 — 遍历 file_info 表，cache 不存在/存在两种决策路径"""
import os
from config import log, DRY_RUN, TARGET_PATH
from db import queries, sync as db_sync
from db.connection import connect
from nfo import ugreen
from nfo.reader import read_nfo
from nfo.writer import write_ugreen_from_db
from sync.strategy import decide_first_sync, decide_from_cache
from models import NfoRecord, VideoMeta, SyncResult, FileRecord
from models import UgreenRecord, PlayHistory, Favorite, Collection
import state as st


def run_sync() -> list[SyncResult]:
    conn = connect()
    results: list[SyncResult] = []
    processed_dirs: set[tuple] = set()
    stats = {"nfo_to_db": 0, "db_to_json": 0, "skip": 0, "error": 0, "cached": 0}

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

            dir_key = _dir_key(folder, fr.season_num, fr.file_name)
            if dir_key in processed_dirs:
                continue
            processed_dirs.add(dir_key)

            # 电视剧：通过 .ugreen.json 处理
            if fr.video_type == 2:
                _process_tv(conn, fr, folder, cache, results, stats)
                continue

            cached_entry = cache.get(fr.category_id)

            # ===== 路径 A: cache 存在 =====
            if cached_entry is not None:
                decision = decide_from_cache(
                    fr.video_ctime, fr.video_utime,
                    cached_entry.get("db_ctime", 0),
                    cached_entry.get("db_utime", 0),
                    db_vid=fr.ug_video_info_id,
                    cache_vid=cached_entry.get("db_vid", 0),
                    db_mtime=fr.max_mtime,
                    cache_mtime=cached_entry.get("max_mtime", 0),
                    db_hash=fr.content_hash,
                    cache_hash=cached_entry.get("content_hash", ""),
                )
                if decision.direction == "skip":
                    stats["cached"] += 1
                    continue

                log.info("  → %s %s", decision.scene, decision.message)
                nfo_path = _find_nfo_for_record(fr)
                result = _exec_cached(conn, fr, folder, nfo_path, decision)
                results.append(result)
                stats[result.direction] = stats.get(result.direction, 0) + 1

                _update_cache(cache, fr)
                continue

            # ===== 路径 B: cache 不存在 → 首次决策 =====
            json_record = ugreen.read_ugreen(folder)
            json_ctime = json_record.ctime if json_record else 0
            decision = decide_first_sync(json_ctime, fr.video_ctime)
            log.info("  → %s %s", decision.scene, decision.message)
            result = _exec_first_sync(conn, fr, folder, json_record, decision)
            results.append(result)
            stats[result.direction] = stats.get(result.direction, 0) + 1
            log.info("  → 结果: direction=%s scene=%s synced=%s",
                     result.direction, result.scene, result.synced)

            if result.synced:
                _update_cache(cache, fr)

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


# ---- 路径 A 执行 ----

def _exec_cached(conn, fr: FileRecord, folder: str, nfo_path: str | None,
                 decision: SyncResult) -> SyncResult:
    """cache 存在时的执行：cache.1 = NFO/JSON→DB / cache.2 = DB→JSON"""
    decision.nfo_path = nfo_path or ""

    if decision.scene == "cache.1":  # 刮削 → 从 NFO + JSON 恢复 DB
        nfo = read_nfo(nfo_path) if nfo_path else None
        if nfo is None:
            nfo = NfoRecord(video_dir=folder, official=VideoMeta())
            log.debug("cache.1: 无有效 NFO，仅从 .ugreen.json 恢复 cat=%s", fr.category_id)
        nfo.category_id = fr.category_id  # 优先用 file_info 中的 category_id
        db_sync.sync_nfo_to_db(conn, nfo)
        log.info("cache.1: 恢复完成, cat=%s", fr.category_id)
        return decision

    # cache.2: 用户编辑 → DB → .ugreen.json
    _write_ugreen_from_db(conn, fr.category_id, folder)
    return decision


# ---- 路径 B 执行 ----

def _exec_first_sync(conn, fr: FileRecord, folder: str,
                     json_record, decision: SyncResult) -> SyncResult:
    """cache 不存在时的首次同步"""
    decision.nfo_path = ""

    if decision.scene == "first.1":  # json.ctime < db.ctime → 恢复
        nfo_path = _find_nfo_for_record(fr)
        nfo = read_nfo(nfo_path) if nfo_path else None
        if nfo is None:
            nfo = NfoRecord(video_dir=folder, official=VideoMeta())
        log.debug("first.1: 恢复 DB, cat=%s", fr.category_id)
        nfo.category_id = fr.category_id
        db_sync.sync_nfo_to_db(conn, nfo)
        return decision

    # first.2 / first.3: DB → .ugreen.json（刷新或新建）
    _write_ugreen_from_db(conn, fr.category_id, folder)
    return decision


# ---- DB → .ugreen.json ----

def _write_ugreen_from_db(conn, category_id: str, folder: str):
    """查询 DB 全量数据并写入 .ugreen.json"""
    db_rec = queries.fetch_video_by_category(conn, category_id)
    if db_rec is None:
        log.warning("DB→JSON: DB 无记录 cat=%s", category_id)
        return

    db_actors = queries.fetch_actors(conn, category_id)
    db_play = queries.fetch_play_history(conn, category_id)
    db_fav = queries.fetch_favorites(conn, category_id)
    db_col = queries.fetch_collection(conn, category_id)

    log.debug("DB→JSON: cat=%s actors=%d play=%d fav=%d col=%s",
              category_id, len(db_actors), len(db_play), len(db_fav),
              db_col["name"] if db_col else "无")

    # 读取旧 .ugreen.json 的 play_history，用于合并历史记录
    old_ug = ugreen.read_ugreen(folder)
    old_ph = old_ug.play_history if old_ug else None
    log.info("play_history 合并准备: 旧=%s 条 new=%d 条",
             len(old_ph) if old_ph else "无", len(db_play))
    write_ugreen_from_db(folder, db_rec, db_play, db_fav, db_col, old_ph_list=old_ph)


# ---- 电视剧 ----

def _process_tv(conn, fr: FileRecord, folder: str,
                cache: dict, results: list, stats: dict):
    """电视剧：通过 .ugreen.json 同步"""
    cached_entry = cache.get(fr.category_id)

    if cached_entry is not None:
        decision = decide_from_cache(
            fr.video_ctime, fr.video_utime,
            cached_entry.get("db_ctime", 0),
            cached_entry.get("db_utime", 0),
            db_vid=fr.ug_video_info_id,
            cache_vid=cached_entry.get("db_vid", 0),
            db_mtime=fr.max_mtime,
            cache_mtime=cached_entry.get("max_mtime", 0),
            db_hash=fr.content_hash,
            cache_hash=cached_entry.get("content_hash", ""),
        )
        if decision.direction == "skip":
            stats["cached"] += 1
            return

        log.info("  → %s %s (TV)", decision.scene, decision.message)
        if decision.scene == "cache.1":
            ug = ugreen.read_ugreen(folder)
            if ug:
                ug.category_id = fr.category_id  # 优先用 file_info 最新值
                _restore_tv_from_ugreen(conn, ug, folder)
                stats["nfo_to_db"] = stats.get("nfo_to_db", 0) + 1
            else:
                stats["error"] = stats.get("error", 0) + 1
        else:
            _dump_tv_to_ugreen(conn, fr.category_id, folder)
            stats["db_to_json"] = stats.get("db_to_json", 0) + 1
        _update_cache(cache, fr)
        return

    # cache 不存在 → 首次同步
    ug = ugreen.read_ugreen(folder)
    if ug:
        log.info("  → 首次同步 TV: .ugreen.json 存在 → 恢复")
        ug.category_id = fr.category_id
        _restore_tv_from_ugreen(conn, ug, folder)
        stats["nfo_to_db"] = stats.get("nfo_to_db", 0) + 1
    else:
        log.info("  → 首次同步 TV: 从 DB 生成 .ugreen.json")
        _dump_tv_to_ugreen(conn, fr.category_id, folder)
        stats["db_to_json"] = stats.get("db_to_json", 0) + 1
    _update_cache(cache, fr)


def _restore_tv_from_ugreen(conn, ug, folder: str):
    """.ugreen.json → DB：ug_video_info 全字段回写 + 剧集 + 扩展数据"""
    from utils import fix_paths_for_video_dir
    fix_paths_for_video_dir(ug, folder)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ug_video_info SET
                 name = %s, pinyin_first = %s, pinyin_full = %s, to9_digit = %s,
                 year = %s, season = %s, introduction = %s,
                 score = %s, douban_id = %s, tmdb_id = %s,
                 style_list = %s, grading = %s,
                 release_date = %s, last_release_date = %s,
                 all_season_episode_num = %s,
                 country_list = %s, type = %s, use_nfo = %s,
                 poster_path = %s, backdrop_path = %s,
                 logo_path = %s, tagline = %s,
                 no_lang_poster_path = %s, no_lang_backdrop_path = %s,
                 language = %s, old_category_id = %s,
                 collection_id = %s, collection_time = %s,
                 media_lib_set_id = %s, last_play_file_path = %s,
                 jp_name = %s, ug_media_id = %s,
                 ctime = %s, utime = %s
               WHERE category_id = %s""",
            (ug.name, ug.pinyin_first, ug.pinyin_full, ug.to9_digit,
             ug.year, ug.season, ug.introduction,
             ug.score, ug.douban_id, ug.tmdb_id,
             ug.style_list, ug.grading,
             ug.release_date, ug.last_release_date,
             ug.all_season_episode_num,
             ug.country_list, ug.type, ug.use_nfo,
             ug.poster_path, ug.backdrop_path,
             ug.logo_path, ug.tagline,
             ug.no_lang_poster_path, ug.no_lang_backdrop_path,
             ug.language, ug.old_category_id,
             ug.collection_id, ug.collection_time,
             ug.media_lib_set_id, ug.last_play_file_path,
             ug.jp_name, ug.ug_media_id,
             ug.ctime, ug.utime, ug.category_id),
        )
    for ep in ug.episodes:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE ug_television_episode SET
                     season = %s, episode = %s, name = %s,
                     overview = %s, cover_path = %s, language = %s,
                     episode_flag = %s, ctime = %s, utime = %s,
                     media_lib_set_id = %s
                   WHERE ug_television_episode_id = %s""",
                (ep.get("season", 0), ep.get("episode", 0), ep.get("name", ""),
                 ep.get("overview", ""), ep.get("cover_path", ""),
                 ep.get("language", ""), ep.get("episode_flag", ""),
                 ep.get("ctime", 0), ep.get("utime", 0),
                 ep.get("media_lib_set_id", 0),
                 ep.get("ug_television_episode_id", 0)),
            )
    if ug.play_history:
        db_sync.upsert_play_history(conn, ug.play_history, folder, "")
    if ug.favorites:
        db_sync.upsert_favorites(conn, ug.category_id, ug.favorites)
    if ug.collection and ug.collection.name:
        db_sync.upsert_collection_for_video(conn, ug.category_id, ug.collection)
    log.info("TV 恢复: cat=%s episodes=%d", ug.category_id, len(ug.episodes))


def _dump_tv_to_ugreen(conn, category_id: str, folder: str):
    """DB → .ugreen.json：电视剧全量写入"""
    db_rec = queries.fetch_video_by_category(conn, category_id)
    if db_rec is None:
        return

    eps = queries.fetch_episodes(conn, category_id)
    phs = queries.fetch_play_history(conn, category_id)
    favs = queries.fetch_favorites(conn, category_id)
    col = queries.fetch_collection(conn, category_id)

    from nfo.writer import _build_ph_list, _merge_play_history
    new_ph = _build_ph_list(phs)
    old_ug = ugreen.read_ugreen(folder)
    if old_ug and old_ug.play_history:
        ph_list = _merge_play_history(old_ug.play_history, new_ph)
        log.info("TV play_history 合并: 旧=%d 新=%d 合并后=%d",
                 len(old_ug.play_history), len(new_ph), len(ph_list))
    else:
        ph_list = new_ph
        log.info("TV play_history: 无旧记录，仅写入 DB 数据 (%d 条)", len(new_ph))

    fav_list = [Favorite(**{k: v for k, v in f.items()}) for f in favs]
    col_obj = None
    if col:
        cats = col.get("category_id_list") or []
        col_obj = Collection(
            name=col.get("name", ""), collection_id=col.get("collection_id", ""),
            tmdb_id=str(col.get("tmdb_id", "0") or "0"),
            pinyin_first=col.get("pinyin_first", ""), pinyin_full=col.get("pinyin_full", ""),
            poster_path=col.get("poster_path", ""), backdrop_path=col.get("backdrop_path", ""),
            language=col.get("language", ""), introduction=col.get("introduction", ""),
            is_manual_create=bool(col.get("is_manual_create")),
            media_lib_set_id=col.get("media_lib_set_id", 0),
            year=col.get("year", 0), score=float(col.get("score", 0) or 0),
            category_id_list=[str(c) for c in cats] if cats else [],
            src_type=col.get("src_type", 0), jp_name=col.get("jp_name", ""),
            cloud_id=col.get("cloud_id", ""), ctime=col.get("ctime", 0), utime=col.get("utime", 0),
        )

    record = UgreenRecord(
        category_id=category_id,
        ug_video_info_id=db_rec.ug_video_info_id,
        media_lib_set_id=db_rec.media_lib_set_id,
        ctime=db_rec.ctime, utime=db_rec.utime,
        name=db_rec.name or "", pinyin_first=db_rec.pinyin_first or "",
        pinyin_full=db_rec.pinyin_full or "", to9_digit=db_rec.to9_digit or "",
        year=db_rec.year, season=db_rec.season,
        introduction=db_rec.introduction or "", score=db_rec.score,
        douban_id=db_rec.douban_id, tmdb_id=db_rec.tmdb_id,
        style_list=db_rec.style_list or [], grading=db_rec.grading,
        release_date=db_rec.release_date,
        last_release_date=db_rec.last_release_date,
        all_season_episode_num=db_rec.all_season_episode_num,
        country_list=db_rec.country_list or [], type=db_rec.type,
        use_nfo=db_rec.use_nfo,
        poster_path=db_rec.poster_path or "",
        backdrop_path=db_rec.backdrop_path or "",
        logo_path=db_rec.logo_path or "", tagline=db_rec.tagline or "",
        no_lang_poster_path=db_rec.no_lang_poster_path or "",
        no_lang_backdrop_path=db_rec.no_lang_backdrop_path or "",
        language=db_rec.language or "",
        old_category_id=db_rec.old_category_id or "",
        collection_id=db_rec.collection_id or "",
        collection_time=db_rec.collection_time,
        last_play_file_path=db_rec.last_play_file_path or "",
        jp_name=db_rec.jp_name or "", ug_media_id=db_rec.ug_media_id or "",
        genre=db_rec.style_list or [],
        episodes=eps, play_history=ph_list,
        favorites=fav_list, collection=col_obj,
    )
    ugreen.write_ugreen(folder, record)


# ---- 辅助 ----

def _dir_key(folder: str, season: int, file_name: str = "") -> tuple:
    if season and file_name:
        return (folder, season, file_name)
    return (folder, season) if season else (folder,)


def _find_nfo_for_record(fr: FileRecord) -> str | None:
    """查找 FileRecord 对应的 NFO 文件（仅用于读取官方字段）。"""
    folder = fr.folder_path
    file_nfo = os.path.splitext(fr.file_name)[0] + ".nfo"
    if fr.video_type == 1:
        candidates = ["movie.nfo", file_nfo]
    elif fr.video_type == 2:
        return None  # 电视剧不用 NFO
    else:
        candidates = [file_nfo, "season.nfo", "tvshow.nfo"]
    for name in candidates:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def _update_cache(cache: dict, fr: FileRecord):
    st.update_cache(fr.category_id, fr.video_ctime, fr.video_utime,
                    cache, db_vid=fr.ug_video_info_id, max_mtime=fr.max_mtime,
                    content_hash=fr.content_hash)


def _log_summary(stats: dict, total: int):
    log.info("======== 同步汇总 ========")
    log.info("  缓存跳过: %d", stats.get("cached", 0))
    log.info("  NFO/JSON → DB: %d", stats.get("nfo_to_db", 0))
    log.info("  DB → JSON: %d", stats.get("db_to_json", 0))
    log.info("  跳过:     %d", stats.get("skip", 0))
    if stats.get("error", 0):
        log.warning("  错误:     %d", stats.get("error", 0))
    log.info("  总计:     %d", total)
    if stats.get("error", 0):
        log.warning("======== %d 条错误，请检查上方日志 ========", stats["error"])
    else:
        log.info("======== 同步完成，无错误 ========")
