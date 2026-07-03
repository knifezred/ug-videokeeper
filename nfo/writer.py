"""ugreen 扩展数据写入 — 全量写入 .ugreen.json，永不写入 NFO"""
import os
from typing import Optional
from config import log, DRY_RUN
from models import DbRecord, PlayHistory, Favorite, Collection
from utils import compute_file_hash
from nfo import ugreen


def write_ugreen_from_db(video_dir: str, db: DbRecord,
                          db_play_history: list,
                          db_favorites: list,
                          db_collection: Optional[dict],
                          old_ph_list: Optional[list] = None):
    """DB → .ugreen.json：全量写入扩展数据 + 官方字段备份"""
    record = _build_ugreen_record(db, db_play_history, db_favorites, db_collection,
                                   db.category_id, video_dir, old_ph_list)
    if DRY_RUN:
        log.info("[DRY RUN] 将写入 .ugreen.json: %s", ugreen.ugreen_path(video_dir))
        return
    ugreen.write_ugreen(video_dir, record)


def _build_ugreen_record(db: DbRecord, db_play_history: list,
                          db_favorites: list, db_collection: Optional[dict],
                          category_id: str, video_dir: str,
                          old_ph_list: Optional[list[PlayHistory]] = None
                          ) -> ugreen.UgreenRecord:
    """从 DB 查询结果构建 UgreenRecord（全表字段写入）。
    若传入 old_ph_list（旧 .ugreen.json 的历史记录），合并新旧 play_history 并去重。
    """
    # play_history：合并新旧
    new_ph = _build_ph_list(db_play_history)
    if old_ph_list and old_ph_list is not None:
        merged = _merge_play_history(old_ph_list, new_ph)
        log.info("合并 play_history: 旧=%d 新=%d 合并后=%d",
                 len(old_ph_list), len(new_ph), len(merged))
        ph_list = merged
    else:
        log.info("play_history: 无旧记录，仅写入 DB 数据 (%d 条)", len(new_ph))
        ph_list = new_ph

    fav_list = [Favorite(**{k: v for k, v in f.items()}) for f in db_favorites]

    col_obj = None
    if db_collection:
        cats = db_collection.get("category_id_list") or []
        col_obj = Collection(
            name=db_collection.get("name", ""),
            collection_id=db_collection.get("collection_id", ""),
            tmdb_id=str(db_collection.get("tmdb_id", "0") or "0"),
            pinyin_first=db_collection.get("pinyin_first", ""),
            pinyin_full=db_collection.get("pinyin_full", ""),
            poster_path=db_collection.get("poster_path", ""),
            backdrop_path=db_collection.get("backdrop_path", ""),
            language=db_collection.get("language", ""),
            introduction=db_collection.get("introduction", ""),
            is_manual_create=bool(db_collection.get("is_manual_create")),
            media_lib_set_id=db_collection.get("media_lib_set_id", 0),
            year=db_collection.get("year", 0),
            score=float(db_collection.get("score", 0) or 0),
            category_id_list=[str(c) for c in cats] if cats else [],
            src_type=db_collection.get("src_type", 0),
            jp_name=db_collection.get("jp_name", ""),
            cloud_id=db_collection.get("cloud_id", ""),
            ctime=db_collection.get("ctime", 0),
            utime=db_collection.get("utime", 0),
        )

    return ugreen.UgreenRecord(
        category_id=category_id or "",
        ug_video_info_id=db.ug_video_info_id,
        media_lib_set_id=db.media_lib_set_id,
        ctime=db.ctime, utime=db.utime,
        # ug_video_info 全字段（除自增主键）
        name=db.name or "",
        pinyin_first=db.pinyin_first or "",
        pinyin_full=db.pinyin_full or "",
        to9_digit=db.to9_digit or "",
        year=db.year, season=db.season,
        introduction=db.introduction or "",
        score=db.score, douban_id=db.douban_id,
        tmdb_id=db.tmdb_id,
        style_list=db.style_list or [],
        grading=db.grading,
        release_date=db.release_date,
        last_release_date=db.last_release_date,
        all_season_episode_num=db.all_season_episode_num,
        country_list=db.country_list or [],
        type=db.type, use_nfo=db.use_nfo,
        poster_path=db.poster_path or "",
        backdrop_path=db.backdrop_path or "",
        logo_path=db.logo_path or "",
        tagline=db.tagline or "",
        no_lang_poster_path=db.no_lang_poster_path or "",
        no_lang_backdrop_path=db.no_lang_backdrop_path or "",
        language=db.language or "",
        old_category_id=db.old_category_id or "",
        collection_id=db.collection_id or "",
        collection_time=db.collection_time,
        last_play_file_path=db.last_play_file_path or "",
        jp_name=db.jp_name or "",
        ug_media_id=db.ug_media_id or "",
        # 扩展
        genre=db.style_list or [],
        play_history=ph_list, favorites=fav_list,
        collection=col_obj,
    )


# ---- play_history 合并 ----

def _build_ph_list(raw: list[dict]) -> list[PlayHistory]:
    """将 DB 原始 dict 列表转为 PlayHistory 对象列表（补算 strm hash）"""
    result = []
    for ph in raw:
        hash_fp = ph.get("hash_fingerprint", "") or ""
        if not hash_fp:
            fn, fp = ph.get("file_name", ""), ph.get("folder_path", "")
            if fn and fp and fn.endswith(".strm") and os.path.isfile(os.path.join(fp, fn)):
                try: hash_fp = compute_file_hash(os.path.join(fp, fn))
                except OSError: pass
        result.append(PlayHistory(
            uid=ph.get("uid", 0), category_id=ph.get("category_id", ""),
            hash_fingerprint=hash_fp, progress=float(ph.get("progress", 0)),
            current_play_time=ph.get("current_play_time", 0),
            last_access_time=ph.get("last_access_time", 0),
            watch_status=ph.get("watch_status", 1),
            media_lib_set_id=ph.get("media_lib_set_id", 0),
            create_time=ph.get("create_time", 0), iso_ts=ph.get("iso_ts", ""),
        ))
    return result


def _ph_eq(a: PlayHistory, b: PlayHistory) -> bool:
    """精确比对两条播放记录的所有字段"""
    return (a.uid == b.uid
            and a.category_id == b.category_id
            and a.hash_fingerprint == b.hash_fingerprint
            and a.progress == b.progress
            and a.current_play_time == b.current_play_time
            and a.last_access_time == b.last_access_time
            and a.watch_status == b.watch_status
            and a.media_lib_set_id == b.media_lib_set_id
            and a.create_time == b.create_time
            and a.iso_ts == b.iso_ts)


def _merge_play_history(old: list[PlayHistory], new: list[PlayHistory]) -> list[PlayHistory]:
    """合并新旧 play_history：取并集，移除全字段完全一致的重复记录。

    不同播放记录即使 (uid, last_access_time) 相同也各自保留，
    只删除所有 10 个字段完全一致的重复项（相同的事件被两次写入的情况）。"""
    merged = old + new
    seen = []
    for ph in merged:
        if not any(_ph_eq(ph, s) for s in seen):
            seen.append(ph)
    return seen
