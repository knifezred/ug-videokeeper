""".ugreen.json — 绿联扩展数据的 JSON 文件读写

替代 NFO <ugreen> 节点 + ugreen_tv.nfo 的自定义 XML 格式。
- 写入：全量覆写 json.dump
- 读取：json.load → UgreenRecord(**data)
"""

import json
import os
from typing import Optional
from config import log
from models import UgreenRecord, PlayHistory, Favorite, Collection


UGREEN_FILE = ".ugreen.json"


def ugreen_path(video_dir: str) -> str:
    """返回 video_dir/.ugreen.json 路径"""
    return os.path.join(video_dir, UGREEN_FILE)


def read_ugreen(video_dir: str) -> Optional[UgreenRecord]:
    """从 .ugreen.json 读取数据，不存在返回 None"""
    path = ugreen_path(video_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        record = UgreenRecord(**data)
        log.debug("读取 .ugreen.json: %s (cat=%s)", path, record.category_id)
        return record
    except (json.JSONDecodeError, IOError, TypeError) as e:
        log.warning(".ugreen.json 解析失败 %s: %s", path, e)
        return None


def write_ugreen(video_dir: str, record: UgreenRecord):
    """写入 .ugreen.json"""
    path = ugreen_path(video_dir)
    data = _to_dict(record)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    log.debug("写入 .ugreen.json: %s (cat=%s)", path, record.category_id)


def _to_dict(record: UgreenRecord) -> dict:
    """将 UgreenRecord 序列化为可 JSON 序列化的 dict"""
    d = {
        "version": record.version,
        "category_id": record.category_id,
        "ug_video_info_id": record.ug_video_info_id,
        "media_lib_set_id": record.media_lib_set_id,
        "ctime": record.ctime,
        "utime": record.utime,
        # ug_video_info 全字段
        "name": record.name,
        "pinyin_first": record.pinyin_first,
        "pinyin_full": record.pinyin_full,
        "to9_digit": record.to9_digit,
        "year": record.year,
        "season": record.season,
        "introduction": record.introduction,
        "score": record.score,
        "douban_id": record.douban_id,
        "tmdb_id": record.tmdb_id,
        "style_list": record.style_list,
        "grading": record.grading,
        "release_date": record.release_date,
        "last_release_date": record.last_release_date,
        "all_season_episode_num": record.all_season_episode_num,
        "country_list": record.country_list,
        "type": record.type,
        "use_nfo": record.use_nfo,
        "poster_path": record.poster_path,
        "backdrop_path": record.backdrop_path,
        "logo_path": record.logo_path,
        "tagline": record.tagline,
        "no_lang_poster_path": record.no_lang_poster_path,
        "no_lang_backdrop_path": record.no_lang_backdrop_path,
        "language": record.language,
        "old_category_id": record.old_category_id,
        "collection_id": record.collection_id,
        "collection_time": record.collection_time,
        "last_play_file_path": record.last_play_file_path,
        "jp_name": record.jp_name,
        "ug_media_id": record.ug_media_id,
        # 扩展
        "genre": record.genre,
    }
    # play_history
    d["play_history"] = [
        {
            "uid": ph.uid,
            "category_id": ph.category_id,
            "hash_fingerprint": ph.hash_fingerprint,
            "progress": ph.progress,
            "current_play_time": ph.current_play_time,
            "last_access_time": ph.last_access_time,
            "watch_status": ph.watch_status,
            "media_lib_set_id": ph.media_lib_set_id,
            "create_time": ph.create_time,
            "iso_ts": ph.iso_ts,
        }
        for ph in record.play_history
    ]
    # favorites
    d["favorites"] = [
        {
            "uid": fav.uid,
            "create_time": fav.create_time,
            "favorites_type": fav.favorites_type,
        }
        for fav in record.favorites
    ]
    # collection
    if record.collection:
        d["collection"] = {
            "name": record.collection.name,
            "collection_id": record.collection.collection_id,
            "tmdb_id": record.collection.tmdb_id,
            "pinyin_first": record.collection.pinyin_first,
            "pinyin_full": record.collection.pinyin_full,
            "poster_path": record.collection.poster_path,
            "backdrop_path": record.collection.backdrop_path,
            "language": record.collection.language,
            "introduction": record.collection.introduction,
            "is_manual_create": record.collection.is_manual_create,
            "media_lib_set_id": record.collection.media_lib_set_id,
            "year": record.collection.year,
            "score": record.collection.score,
            "category_id_list": record.collection.category_id_list,
            "src_type": record.collection.src_type,
            "jp_name": record.collection.jp_name,
            "cloud_id": record.collection.cloud_id,
            "ctime": record.collection.ctime,
            "utime": record.collection.utime,
        }
    # episodes (电视剧专用)
    if record.episodes:
        d["episodes"] = record.episodes
    return d
