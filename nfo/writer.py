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
                          db_collection: Optional[dict]):
    """DB → .ugreen.json：全量写入扩展数据 + 官方字段备份"""
    record = _build_ugreen_record(db, db_play_history, db_favorites, db_collection,
                                   db.category_id, video_dir)
    if DRY_RUN:
        log.info("[DRY RUN] 将写入 .ugreen.json: %s", ugreen.ugreen_path(video_dir))
        return
    ugreen.write_ugreen(video_dir, record)


def _build_ugreen_record(db: DbRecord, db_play_history: list,
                          db_favorites: list, db_collection: Optional[dict],
                          category_id: str, video_dir: str) -> ugreen.UgreenRecord:
    """从 DB 查询结果构建 UgreenRecord（全表字段写入）"""
    # play_history（补算 strm hash）
    ph_list = []
    for ph in db_play_history:
        hash_fp = ph.get("hash_fingerprint", "") or ""
        if not hash_fp:
            fn, fp = ph.get("file_name", ""), ph.get("folder_path", "")
            if fn and fp and fn.endswith(".strm") and os.path.isfile(os.path.join(fp, fn)):
                try: hash_fp = compute_file_hash(os.path.join(fp, fn))
                except OSError: pass
        ph_list.append(PlayHistory(
            uid=ph.get("uid", 0), category_id=ph.get("category_id", ""),
            hash_fingerprint=hash_fp, progress=float(ph.get("progress", 0)),
            current_play_time=ph.get("current_play_time", 0),
            last_access_time=ph.get("last_access_time", 0),
            watch_status=ph.get("watch_status", 1),
            media_lib_set_id=ph.get("media_lib_set_id", 0),
            create_time=ph.get("create_time", 0), iso_ts=ph.get("iso_ts", ""),
        ))

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
        type="tvshow" if db.season else "movie",
        category_id=category_id or "",
        ug_video_info_id=db.ug_video_info_id,
        media_lib_set_id=db.media_lib_set_id,
        ctime=db.ctime, utime=db.utime,
        name=db.name or "", year=db.year,
        introduction=db.introduction or "", score=db.score,
        tmdb_id=db.tmdb_id, douban_id=db.douban_id,
        style_list=db.style_list or [], grading=db.grading,
        release_date=db.release_date,
        all_season_episode_num=db.all_season_episode_num,
        genre=db.style_list or [],
        play_history=ph_list, favorites=fav_list,
        collection=col_obj, season=db.season,
    )
