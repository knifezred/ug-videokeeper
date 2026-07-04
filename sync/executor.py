"""同步执行器 — 遍历 file_info 表，cache 不存在/存在两种决策路径"""
import os
import sqlite3
from config import log, DRY_RUN, TARGET_PATH
from db import queries, sync as db_sync
from db.connection import connect
from nfo import ugreen
from nfo.reader import read_nfo
from nfo.writer import write_ugreen_from_db
from sync.strategy import decide_first_sync, decide_from_cache
from models import NfoRecord, VideoMeta, FileRecord
from models import UgreenRecord, PlayHistory, Favorite, Collection
import state as st


def run_sync():
    conn = connect()
    sqlite_conn = sqlite3.connect(st._DB_PATH)
    sqlite_conn.execute("""CREATE TABLE IF NOT EXISTS sync_cache (
        category_id TEXT PRIMARY KEY, data TEXT NOT NULL
    )""")

    stats = {"nfo_to_db": 0, "db_to_json": 0, "skip": 0, "error": 0, "cached": 0}
    seen_cats: set[str] = set()
    _progress_count = 0
    log.info("======== 同步开始 ========")

    st.migrate_from_json()

    try:
        for batch in queries.fetch_all_file_info_cursor(conn, TARGET_PATH):
            cat_ids = list({fr.category_id for fr in batch})
            cache = st.load_batch(sqlite_conn, cat_ids)

            for fr in batch:
                folder = fr.folder_path
                if not folder or not os.path.isdir(folder):
                    continue
                if fr.category_id in seen_cats:
                    continue
                seen_cats.add(fr.category_id)
                _progress_count += 1
                if _progress_count % 10000 == 0:
                    log.info("进度: %d 条", _progress_count)

                # 电视剧
                if fr.video_type == 2:
                    _process_tv(conn, fr, folder, cache, stats)
                    continue

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
                        continue

                    log.debug("  → %s %s", decision.scene, decision.message)
                    nfo_path = _find_nfo_for_record(fr)
                    _exec_cached(conn, fr, folder, nfo_path, decision)
                    stats[decision.direction] = stats.get(decision.direction, 0) + 1
                    _update_cache(cache, fr)
                    continue

                # cache 不存在 → 首次决策
                json_record = ugreen.read_ugreen(folder)
                json_ctime = json_record.ctime if json_record else 0
                decision = decide_first_sync(json_ctime, fr.video_ctime)
                log.debug("  → %s %s", decision.scene, decision.message)
                _exec_first_sync(conn, fr, folder, json_record, decision)
                stats[decision.direction] = stats.get(decision.direction, 0) + 1
                if decision.direction != "skip":
                    _update_cache(cache, fr)

            if not DRY_RUN:
                st.save_batch(sqlite_conn, cache)
                sqlite_conn.commit()

        if not DRY_RUN:
            conn.commit()
            log.info("DB 已提交，SQLite 缓存已保存")
        else:
            conn.rollback()
            log.info("[DRY RUN] 跳过写入，缓存未保存")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        sqlite_conn.close()

    _log_summary(stats)


# ---- 路径 A 执行 ----

def _exec_cached(conn, fr: FileRecord, folder: str, nfo_path: str | None,
                 decision):
    """cache 存在时的执行：cache.1 = JSON→DB / cache.2 = DB→JSON"""
    if decision.scene == "cache.1":  # 刮削 → 从 .ugreen.json 恢复 DB
        nfo = read_nfo(nfo_path) if nfo_path else None
        if nfo is None:
            nfo = NfoRecord(video_dir=folder, official=VideoMeta())
            log.debug("cache.1: 无有效 NFO，仅从 .ugreen.json 恢复 cat=%s", fr.category_id)
        nfo.category_id = fr.category_id
        db_sync.sync_nfo_to_db(conn, nfo)
        log.debug("cache.1: 恢复完成, cat=%s", fr.category_id)
        return

    # cache.2: 用户编辑 → DB → .ugreen.json
    _write_ugreen_from_db(conn, fr.category_id, folder)


# ---- 路径 B 执行 ----

def _exec_first_sync(conn, fr: FileRecord, folder: str,
                     json_record, decision):
    """cache 不存在时的首次同步"""
    if decision.scene == "first.1":  # json.ctime < db.ctime → 恢复
        nfo_path = _find_nfo_for_record(fr)
        nfo = read_nfo(nfo_path) if nfo_path else None
        if nfo is None:
            nfo = NfoRecord(video_dir=folder, official=VideoMeta())
        log.debug("first.1: 恢复 DB, cat=%s", fr.category_id)
        nfo.category_id = fr.category_id
        db_sync.sync_nfo_to_db(conn, nfo)
        return

    # first.2 / first.3: DB → .ugreen.json（刷新或新建）
    _write_ugreen_from_db(conn, fr.category_id, folder)


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

    # 读取旧 .ugreen.json 的 play_history 和 nfo_snapshot，用于合并
    old_ug = ugreen.read_ugreen(folder)
    old_ph = old_ug.play_history if old_ug else None
    old_snap = old_ug.nfo_snapshot if old_ug else None
    log.debug("play_history 合并准备: 旧=%s 条 new=%d 条",
             len(old_ph) if old_ph else "无", len(db_play))
    write_ugreen_from_db(folder, db_rec, db_play, db_fav, db_col,
                         old_ph_list=old_ph, old_nfo_snapshot=old_snap)


# ---- 电视剧 ----

def _process_tv(conn, fr: FileRecord, folder: str,
                cache: dict, stats: dict):
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

        log.debug("  → %s %s (TV)", decision.scene, decision.message)
        if decision.scene == "cache.1":
            ug = ugreen.read_ugreen(folder)
            if ug:
                cat_changed = (ug.category_id != fr.category_id)
                ug.category_id = fr.category_id  # 优先用 file_info 最新值
                _restore_tv_from_ugreen(conn, ug, folder, cat_changed=cat_changed)
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
        log.debug("  → 首次同步 TV: .ugreen.json 存在 → 恢复")
        cat_changed = (ug.category_id != fr.category_id)
        ug.category_id = fr.category_id
        _restore_tv_from_ugreen(conn, ug, folder, cat_changed=cat_changed)
        stats["nfo_to_db"] = stats.get("nfo_to_db", 0) + 1
    else:
        log.debug("  → 首次同步 TV: 从 DB 生成 .ugreen.json")
        _dump_tv_to_ugreen(conn, fr.category_id, folder)
        stats["db_to_json"] = stats.get("db_to_json", 0) + 1
    _update_cache(cache, fr)


def _restore_tv_from_ugreen(conn, ug, folder: str, cat_changed: bool = False):
    """.ugreen.json → DB：ug_video_info 全字段回写 + 剧集 + 扩展数据"""
    if cat_changed:
        from utils import fix_paths_for_video_dir
        fix_paths_for_video_dir(ug, folder, cat_changed=True)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ug_video_info SET
                 name = %s, introduction = %s, score = %s,
                 release_date = %s, country_list = %s, style_list = %s,
                 poster_path = %s, backdrop_path = %s, logo_path = %s,
                 ctime = %s, utime = %s
               WHERE category_id = %s""",
            (ug.name, ug.introduction, ug.score,
             ug.release_date, ug.country_list, ug.style_list,
             ug.poster_path, ug.backdrop_path, ug.logo_path,
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
    log.debug("TV 恢复: cat=%s episodes=%d", ug.category_id, len(ug.episodes))


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
    old_snap = old_ug.nfo_snapshot if old_ug else None
    if old_ug and old_ug.play_history:
        ph_list = _merge_play_history(old_ug.play_history, new_ph)
        log.debug("TV play_history 合并: 旧=%d 新=%d 合并后=%d",
                 len(old_ug.play_history), len(new_ph), len(ph_list))
    else:
        ph_list = new_ph
        log.debug("TV play_history: 无旧记录，仅写入 DB 数据 (%d 条)", len(new_ph))

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
        # ug_video_info 全量字段备份
        name=db_rec.name or "",
        pinyin_first=db_rec.pinyin_first or "",
        pinyin_full=db_rec.pinyin_full or "",
        to9_digit=db_rec.to9_digit or "",
        year=db_rec.year, season=db_rec.season,
        introduction=db_rec.introduction or "",
        score=db_rec.score,
        douban_id=db_rec.douban_id, tmdb_id=db_rec.tmdb_id,
        style_list=db_rec.style_list or [],
        grading=db_rec.grading,
        release_date=db_rec.release_date,
        last_release_date=db_rec.last_release_date,
        all_season_episode_num=db_rec.all_season_episode_num,
        country_list=db_rec.country_list or [],
        type=db_rec.type, use_nfo=db_rec.use_nfo,
        poster_path=db_rec.poster_path or "",
        backdrop_path=db_rec.backdrop_path or "",
        logo_path=db_rec.logo_path or "",
        tagline=db_rec.tagline or "",
        no_lang_poster_path=db_rec.no_lang_poster_path or "",
        no_lang_backdrop_path=db_rec.no_lang_backdrop_path or "",
        language=db_rec.language or "",
        old_category_id=db_rec.old_category_id or "",
        collection_id=db_rec.collection_id or "",
        collection_time=db_rec.collection_time,
        last_play_file_path=db_rec.last_play_file_path or "",
        jp_name=db_rec.jp_name or "",
        ug_media_id=db_rec.ug_media_id or "",
        # 扩展
        episodes=eps, play_history=ph_list,
        favorites=fav_list, collection=col_obj,
        nfo_snapshot=old_snap,
    )
    if DRY_RUN:
        log.info("[DRY RUN] 将写入 .ugreen.json: %s", ugreen.ugreen_path(folder))
    else:
        ugreen.write_ugreen(folder, record)


# ---- 辅助 ----

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


def _log_summary(stats: dict):
    log.info("======== 同步汇总 ========")
    log.info("  缓存跳过: %d", stats.get("cached", 0))
    log.info("  NFO/JSON → DB: %d", stats.get("nfo_to_db", 0))
    log.info("  DB → JSON: %d", stats.get("db_to_json", 0))
    if stats.get("error", 0):
        log.warning("  错误:     %d", stats.get("error", 0))
    if stats.get("error", 0):
        log.warning("======== %d 条错误，请检查上方日志 ========", stats["error"])
    else:
        log.info("======== 同步完成，无错误 ========")
