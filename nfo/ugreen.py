""".ugreen.json — 绿联扩展数据的 JSON 文件读写

替代 NFO <ugreen> 节点 + ugreen_tv.nfo 的自定义 XML 格式。
- 写入：全量覆写 json.dump
- 读取：json.load → UgreenRecord(**data)
- 旧格式兼容：从 NFO <ugreen> 抽取数据
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
        "type": record.type,
        "category_id": record.category_id,
        "ug_video_info_id": record.ug_video_info_id,
        "media_lib_set_id": record.media_lib_set_id,
        "ctime": record.ctime,
        "utime": record.utime,
        "name": record.name,
        "year": record.year,
        "introduction": record.introduction,
        "score": record.score,
        "tmdb_id": record.tmdb_id,
        "douban_id": record.douban_id,
        "style_list": record.style_list,
        "grading": record.grading,
        "release_date": record.release_date,
        "all_season_episode_num": record.all_season_episode_num,
        "genre": record.genre,
        "season": record.season,
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


def is_nfo_newer_than_ugreen(nfo_path: str, ugreen_record: UgreenRecord) -> bool:
    """NFO 文件 mtime > .ugreen.json.ctime？用户可能手动编辑了 NFO"""
    try:
        nfo_mtime = int(os.path.getmtime(nfo_path))
    except OSError:
        return False
    return nfo_mtime > ugreen_record.ctime


def extract_ugreen_from_nfo(nfo_path: str) -> Optional[dict]:
    """从 NFO 的 <ugreen> 节点抽取数据（旧格式兼容）。
    返回可直接构造 UgreenRecord 的 dict，或 None。"""
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
    except (ET.ParseError, FileNotFoundError):
        return None

    ug = root.find("ugreen")
    if ug is None:
        return None

    data = {"ctime": _int_text(ug, "ctime"),
            "utime": _int_text(ug, "utime"),
            "category_id": _text(ug, "category_id"),
            "ug_video_info_id": _int_text(ug, "ug_video_info_id"),
            "media_lib_set_id": _int_text(ug, "media_lib_set_id")}

    # genre
    genres = [g.text.strip() for g in ug.findall("genre") if g.text]
    if genres:
        data["genre"] = genres

    # play_history
    ph_list = []
    for ph_el in ug.findall("play_history"):
        ph_list.append({
            "uid": _int_text(ph_el, "uid") or 0,
            "category_id": _text(ph_el, "category_id") or "",
            "hash_fingerprint": _text(ph_el, "hash_fingerprint") or "",
            "progress": _float_text(ph_el, "progress") or 0.0,
            "current_play_time": _int_text(ph_el, "current_play_time") or 0,
            "last_access_time": _int_text(ph_el, "last_access_time") or 0,
            "watch_status": _int_text(ph_el, "watch_status") or 1,
            "media_lib_set_id": _int_text(ph_el, "media_lib_set_id") or 0,
            "create_time": _int_text(ph_el, "create_time") or 0,
            "iso_ts": _text(ph_el, "iso_ts") or "",
        })
    if ph_list:
        data["play_history"] = ph_list

    # favorites
    fav_list = []
    for fav_el in ug.findall("favorites"):
        fav_list.append({
            "uid": _int_text(fav_el, "uid") or 0,
            "create_time": _int_text(fav_el, "create_time") or 0,
            "favorites_type": _int_text(fav_el, "favorites_type") or 1,
        })
    if fav_list:
        data["favorites"] = fav_list

    # collection
    col_el = ug.find("collection")
    if col_el is not None:
        cat_ids = [c.text.strip() for c in col_el.findall("category_id") if c.text]
        data["collection"] = {
            "name": _text(col_el, "name") or "",
            "collection_id": _text(col_el, "collection_id") or "",
            "tmdb_id": _text(col_el, "tmdb_id") or "0",
            "pinyin_first": _text(col_el, "pinyin_first") or "",
            "pinyin_full": _text(col_el, "pinyin_full") or "",
            "poster_path": _text(col_el, "poster_path") or "",
            "backdrop_path": _text(col_el, "backdrop_path") or "",
            "language": _text(col_el, "language") or "",
            "introduction": _text(col_el, "introduction") or "",
            "is_manual_create": _text(col_el, "is_manual_create") == "true",
            "media_lib_set_id": _int_text(col_el, "media_lib_set_id") or 0,
            "year": _int_text(col_el, "year") or 0,
            "score": _float_text(col_el, "score") or 0.0,
            "category_id_list": cat_ids,
            "src_type": _int_text(col_el, "src_type") or 0,
            "jp_name": _text(col_el, "jp_name") or "",
            "cloud_id": _text(col_el, "cloud_id") or "",
            "ctime": _int_text(col_el, "ctime") or 0,
            "utime": _int_text(col_el, "utime") or 0,
        }

    log.debug("从 NFO 抽取 ugreen 数据: %s → %d 字段", nfo_path, len(data))
    return data


def _text(el, tag: str) -> str:
    sub = el.find(tag)
    return sub.text.strip() if sub is not None and sub.text else ""


def _int_text(el, tag: str) -> int:
    sub = el.find(tag)
    try:
        return int(sub.text.strip()) if sub is not None and sub.text else 0
    except (ValueError, TypeError):
        return 0


def _float_text(el, tag: str) -> float:
    sub = el.find(tag)
    try:
        return float(sub.text.strip()) if sub is not None and sub.text else 0.0
    except (ValueError, TypeError):
        return 0.0
