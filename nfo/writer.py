"""ugreen 扩展数据写入 — 全量写入 .ugreen.json，永不写入 NFO"""
import os
from dataclasses import fields as dc_fields
from typing import Optional
from config import log, DRY_RUN
from models import DbRecord, PlayHistory, Favorite, Collection, Actor
from utils import compute_file_hash
from nfo import ugreen


def write_ugreen_from_db(video_dir: str, db: DbRecord,
                          db_play_history: list,
                          db_favorites: list,
                          db_collection: Optional[dict],
                          old_ph_list: Optional[list] = None,
                          old_nfo_snapshot: Optional[dict] = None,
                          db_actors: Optional[list] = None):
    """DB → .ugreen.json：全量写入扩展数据 + 官方字段备份"""
    record = _build_ugreen_record(db, db_play_history, db_favorites, db_collection,
                                   video_dir, old_ph_list,
                                   old_nfo_snapshot, db_actors)
    if DRY_RUN:
        log.info("[DRY RUN] 将写入 .ugreen.json: %s", ugreen.ugreen_path(video_dir))
        return
    ugreen.write_ugreen(video_dir, record)


def _build_ugreen_record(db: DbRecord, db_play_history: list,
                          db_favorites: list, db_collection: Optional[dict],
                          video_dir: str,
                          old_ph_list: Optional[list[PlayHistory]] = None,
                          old_nfo_snapshot: Optional[dict] = None,
                          db_actors: Optional[list] = None
                          ) -> ugreen.UgreenRecord:
    """从 DB 查询结果构建 UgreenRecord（全表字段写入）。
    若传入 old_ph_list（旧 .ugreen.json 的历史记录），合并新旧 play_history 并去重。
    """
    # play_history：合并新旧
    new_ph = _build_ph_list(db_play_history)
    if old_ph_list and old_ph_list is not None:
        merged = _merge_play_history(old_ph_list, new_ph)
        log.debug("合并 play_history: 旧=%d 新=%d 合并后=%d",
                 len(old_ph_list), len(new_ph), len(merged))
        ph_list = merged
    else:
        log.debug("play_history: 无旧记录，仅写入 DB 数据 (%d 条)", len(new_ph))
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

    # 演员：DB 原始 dict → Actor 列表（备份到 .ugreen.json）
    actor_list = [
        Actor(name=a.get("name", ""), role=a.get("role", ""),
              tmdbid=a.get("tmdb_id", 0))
        for a in (db_actors or [])
    ]

    # ug_video_info 全量字段：直接从 DbRecord 拷贝（单一来源，消除手写映射）
    common = {f.name: getattr(db, f.name) for f in dc_fields(DbRecord)}
    return ugreen.UgreenRecord(
        **common,
        # 扩展数据
        play_history=ph_list, favorites=fav_list,
        collection=col_obj, actors=actor_list,
        nfo_snapshot=old_nfo_snapshot,
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


def _merge_play_history(old: list[PlayHistory], new: list[PlayHistory]) -> list[PlayHistory]:
    """合并新旧 play_history：以 (uid, hash_fingerprint, last_access_time) 唯一标识一次播放。

    - 匹配到：用 DB 数据替换 JSON 旧记录（DB 有最新播放进度）
    - 未匹配到的 DB 记录：追加为新播放记录
    - 未匹配到的 JSON 历史记录：保留
    """
    # 构建 old 索引: (uid, hash, last_access_time) → index
    old_index: dict[tuple, int] = {}
    for i, ph in enumerate(old):
        key = (ph.uid, ph.hash_fingerprint or "", ph.last_access_time)
        old_index[key] = i

    result = list(old)

    for new_ph in new:
        fp = new_ph.hash_fingerprint or ""
        key = (new_ph.uid, fp, new_ph.last_access_time)
        if key in old_index:
            # 同一次播放 → 用 DB 数据替换（DB 有最新进度）
            result[old_index[key]] = new_ph
        else:
            # 新的播放记录 → 追加
            result.append(new_ph)

    return result
