"""NFO 文件写入 — 将 NfoRecord 序列化为 XML"""
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Optional
from config import log, DRY_RUN
from models import NfoRecord, DbRecord, Actor, PlayHistory, Favorite, Collection


def write_nfo(nfo: NfoRecord) -> bool:
    """将 NfoRecord 写入 nfo_path（调用方负责设置正确的路径）"""
    if DRY_RUN:
        log.info("[DRY RUN] 将写入 %s", nfo.nfo_path)
        return True

    nfo_path = nfo.nfo_path
    root_tag = {
        "movie": "movie", "tvshow": "tvshow",
        "season": "season", "episode": "episodedetails",
    }.get(nfo.nfo_type, "movie")

    root = _build_official(nfo, root_tag)
    _build_ugreen(nfo, root)

    xml_str = _pretty_xml(root)
    os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
    with open(nfo_path, "w", encoding="utf-8") as f:
        f.write(xml_str)
    log.info("写入 NFO: %s", nfo_path)
    return True


def write_nfo_from_db(nfo: NfoRecord, db: DbRecord,
                       db_actors: list, db_play_history: list,
                       db_favorites: list, db_collection: Optional[dict]):
    """
    从数据库数据构建 NfoRecord 并写入 NFO。
    (sync direction: DB → NFO)
    """
    # 用 DB 数据覆写 official
    o = nfo.official
    o.title = db.name
    o.year = db.year
    o.releasedate = _date_str(db.release_date)
    o.rating = db.score
    o.plot = db.introduction
    o.tmdbid = db.tmdb_id
    o.doubanid = db.douban_id
    o.mpaa = _mpaa_str(db.grading)
    o.country = db.country_list or []
    o.genre = db.style_list or []
    o.season = db.season
    o.all_season_episode_num = db.all_season_episode_num

    # actors
    o.actors = []
    for a in db_actors:
        o.actors.append(Actor(
            name=a.get("name", ""),
            role=a.get("role", ""),
            tmdbid=a.get("tmdb_id", 0),
        ))

    # ugreen: play_history / favorites / collection
    ug = nfo.ugreen
    ug.play_history = []
    for ph in db_play_history:
        ug.play_history.append(PlayHistory(
            uid=ph.get("uid", 0),
            progress=float(ph.get("progress", 0)),
            current_play_time=ph.get("current_play_time", 0),
            last_access_time=ph.get("last_access_time", 0),
            watch_status=ph.get("watch_status", 1),
        ))

    ug.favorites = []
    for fav in db_favorites:
        ug.favorites.append(Favorite(
            uid=fav.get("uid", 0),
            create_time=fav.get("create_time", 0),
            favorites_type=fav.get("favorites_type", 1),
        ))

    if db_collection:
        ug.collection = Collection(
            name=db_collection.get("name", ""),
            tmdbid=int(db_collection.get("tmdb_id", 0) or 0),
        )

    ug.ug_video_info_id = db.ug_video_info_id
    ug.ctime = db.ctime
    ug.utime = db.utime

    write_nfo(nfo)


# ---- XML builders ----

def _build_official(nfo: NfoRecord, root_tag: str) -> ET.Element:
    root = ET.Element(root_tag)
    o = nfo.official

    _sub(root, "title", o.title)
    if o.year:
        _sub(root, "year", str(o.year))
    _sub(root, "releasedate", o.releasedate)
    if o.rating:
        _sub(root, "rating", str(o.rating))
    _sub(root, "plot", o.plot)
    if o.tmdbid:
        _sub(root, "tmdbid", str(o.tmdbid))
    if o.doubanid:
        _sub(root, "doubanid", str(o.doubanid))
    for c in o.country:
        _sub(root, "country", c)
    for g in o.genre:
        _sub(root, "genre", g)
    _sub(root, "mpaa", o.mpaa)

    # 电视剧专用
    if o.season:
        _sub(root, "season", str(o.season))
    if o.episode:
        _sub(root, "episode", str(o.episode))
    if o.seasonnumber:
        _sub(root, "seasonnumber", str(o.seasonnumber))
    if o.all_season_episode_num:
        _sub(root, "all_season_episode_num", str(o.all_season_episode_num))

    for a in o.actors:
        a_el = ET.SubElement(root, "actor")
        _sub(a_el, "name", a.name)
        _sub(a_el, "role", a.role)
        if a.tmdbid:
            _sub(a_el, "tmdbid", str(a.tmdbid))

    return root


def _build_ugreen(nfo: NfoRecord, root: ET.Element):
    ug = ET.SubElement(root, "ugreen")
    ug_meta = nfo.ugreen

    _sub(ug, "ug_video_info_id", str(ug_meta.ug_video_info_id))
    _sub(ug, "category_id", ug_meta.category_id)
    _sub(ug, "use_nfo", str(ug_meta.use_nfo))
    _sub(ug, "media_lib_set_id", str(ug_meta.media_lib_set_id))

    if ug_meta.collection:
        col = ET.SubElement(ug, "collection")
        _sub(col, "name", ug_meta.collection.name)
        if ug_meta.collection.tmdbid:
            _sub(col, "tmdbid", str(ug_meta.collection.tmdbid))

    for ph in ug_meta.play_history:
        ph_el = ET.SubElement(ug, "play_history")
        _sub(ph_el, "uid", str(ph.uid))
        _sub(ph_el, "progress", str(ph.progress))
        _sub(ph_el, "current_play_time", str(ph.current_play_time))
        _sub(ph_el, "last_access_time", str(ph.last_access_time))
        _sub(ph_el, "watch_status", str(ph.watch_status))

    for fav in ug_meta.favorites:
        fav_el = ET.SubElement(ug, "favorites")
        _sub(fav_el, "uid", str(fav.uid))
        _sub(fav_el, "create_time", str(fav.create_time))
        _sub(fav_el, "favorites_type", str(fav.favorites_type))

    if ug_meta.fileinfo:
        fi = ET.SubElement(ug, "fileinfo")
        sd = ET.SubElement(fi, "streamdetails")
        v = ET.SubElement(sd, "video")
        _sub(v, "width", str(ug_meta.fileinfo.width))
        _sub(v, "height", str(ug_meta.fileinfo.height))
        _sub(v, "durationinseconds", str(ug_meta.fileinfo.duration))
        if ug_meta.fileinfo.codec:
            a = ET.SubElement(sd, "audio")
            _sub(a, "codec", ug_meta.fileinfo.codec)
            _sub(a, "channels", str(ug_meta.fileinfo.channels))

    _sub(ug, "ctime", str(ug_meta.ctime))
    _sub(ug, "utime", str(ug_meta.utime))


def _sub(parent, tag: str, text: str):
    if text:
        el = ET.SubElement(parent, tag)
        el.text = text


def _pretty_xml(root: ET.Element) -> str:
    raw = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(raw)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + \
           dom.documentElement.toprettyxml(indent="  ")


def _mpaa_str(grading: int) -> str:
    mapping = {1: "G", 2: "PG", 3: "PG-13", 4: "R", 5: "NC-17"}
    return mapping.get(grading, "")


def _date_str(timestamp: int) -> str:
    """Unix 时间戳 → 'YYYY-MM-DD'"""
    if not timestamp or timestamp <= 0:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
