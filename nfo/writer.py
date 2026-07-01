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

    try:
        root = _build_official(nfo, root_tag)
        _build_ugreen(nfo, root)
        xml_str = _pretty_xml(root)
    except Exception:
        log.error("write_nfo 构建 XML 失败: %s (type=%s cat=%s) title=%r",
                  nfo_path, nfo.nfo_type, nfo.ugreen.category_id,
                  nfo.official.title[:80])
        raise

    os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
    with open(nfo_path, "w", encoding="utf-8") as f:
        f.write(xml_str)
    log.info("写入 NFO: %s", nfo_path)
    return True


def write_nfo_from_db(nfo: NfoRecord, db: DbRecord,
                       db_actors: list, db_play_history: list,
                       db_favorites: list, db_collection: Optional[dict]):
    """
    DB → NFO: XML 补丁模式更新。
    - 官方字段: 更新同名 XML 元素的值，不删除不认识的元素
    - <ugreen>: 整体替换
    - 不存在则全量生成
    """
    # ---- ugreen ----
    ug = nfo.ugreen
    ug.ug_video_info_id = db.ug_video_info_id
    ug.ctime = db.ctime
    ug.utime = db.utime
    ug.genre = db.style_list or []

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
    else:
        ug.collection = None

    # ---- official ----
    o = nfo.official
    o.title = db.name or ""
    o.year = db.year
    o.releasedate = _date_str(db.release_date)
    o.rating = db.score
    o.plot = db.introduction or ""
    o.tmdbid = db.tmdb_id
    o.doubanid = db.douban_id
    o.mpaa = _mpaa_str(db.grading)
    o.season = db.season
    o.all_season_episode_num = db.all_season_episode_num

    if not os.path.isfile(nfo.nfo_path):
        write_nfo(nfo)
    else:
        _patch_nfo(nfo)


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

    for g in ug_meta.genre:
        _sub(ug, "genre", g)

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


def _sub(parent, tag: str, text):
    if not text and text != 0:
        return
    el = ET.SubElement(parent, tag)
    try:
        el.text = text if isinstance(text, str) else str(text)
    except TypeError:
        log.error("_sub 序列化失败: parent=<%s> tag=<%s> value=%r type=%s",
                  parent.tag, tag, text, type(text).__name__)
        raise


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


def _patch_nfo(nfo: NfoRecord):
    """XML 补丁模式：用 minidom 解析（保留 CDATA），更新字段 + 替换 <ugreen>。

    title/plot 写入 CDATA 包裹；originaltitle/originalplot/sorttitle/outline 不覆盖。
    """
    nfo_path = nfo.nfo_path
    try:
        dom = minidom.parse(nfo_path)
        root = dom.documentElement
    except Exception as e:
        log.warning("XML 补丁解析失败 %s: %s，回退到全量写入", nfo_path, e)
        write_nfo(nfo)
        return

    o = nfo.official

    try:
        _set_dom_cdata(dom, root, "title", o.title)
    except Exception:
        log.error("_patch_nfo: title 写入失败 nfo=%s", nfo_path)
        raise
    try:
        _set_dom_cdata(dom, root, "plot", o.plot)
    except Exception:
        log.error("_patch_nfo: plot 写入失败 nfo=%s", nfo_path)
        raise
        _set_dom_text(dom, root, "year", str(o.year) if o.year else "")
        _set_dom_text(dom, root, "releasedate", o.releasedate)
        _set_dom_text(dom, root, "rating", str(o.rating) if o.rating else "")
        _set_dom_text(dom, root, "tmdbid", str(o.tmdbid) if o.tmdbid else "")
        _set_dom_text(dom, root, "doubanid", str(o.doubanid) if o.doubanid else "")
        if nfo.nfo_type != "movie":
            _set_dom_text(dom, root, "season", str(o.season) if o.season else "")
            _set_dom_text(dom, root, "episode", str(o.episode) if o.episode else "")
            _set_dom_text(dom, root, "seasonnumber", str(o.seasonnumber) if o.seasonnumber else "")
            _set_dom_text(dom, root, "all_season_episode_num",
                          str(o.all_season_episode_num) if o.all_season_episode_num else "")
    except Exception:
        log.error("_patch_nfo: 单值字段写入失败 nfo=%s title=%r year=%r",
                  nfo_path, o.title, o.year)
        raise

    try:
        _replace_dom_element(root, "ugreen", _build_ugreen_dom(nfo, dom))
    except Exception:
        log.error("_patch_nfo: ugreen 写入失败 nfo=%s cat=%r vid=%r",
                  nfo_path, nfo.ugreen.category_id, nfo.ugreen.ug_video_info_id)
        raise

    with open(nfo_path, "w", encoding="utf-8") as f:
        f.write(dom.toprettyxml(indent="  "))
    log.info("更新 NFO: %s", nfo_path)


def _set_dom_cdata(dom, parent, tag: str, text: str):
    """更新或创建子元素，文本用 CDATA 包裹。空文本跳过。"""
    if not text:
        return
    _remove_child(parent, tag)
    el = dom.createElement(tag)
    safe = text.replace("]]>", "]]&gt;")
    try:
        el.appendChild(dom.createCDATASection(safe))
    except Exception:
        log.error("_set_dom_cdata 失败: tag=%s text[:100]=%r", tag, text[:100])
        raise
    parent.appendChild(el)


def _set_dom_text(dom, parent, tag: str, text: str):
    """更新或创建子元素，纯文本。空文本跳过。"""
    if not text:
        return
    _remove_child(parent, tag)
    el = dom.createElement(tag)
    el.appendChild(dom.createTextNode(text))
    parent.appendChild(el)


def _remove_child(parent, tag: str):
    """删除 parent 下所有 tag 子元素。"""
    for old in list(parent.getElementsByTagName(tag)):
        parent.removeChild(old)


def _replace_dom_element(parent, tag: str, new_child):
    """替换 parent 下指定 tag 元素为新元素。"""
    _remove_child(parent, tag)
    parent.appendChild(new_child)


def _build_ugreen_dom(nfo: NfoRecord, dom) -> "minidom.Element":
    """构建 <ugreen> DOM 元素。"""
    ug = dom.createElement("ugreen")
    ugm = nfo.ugreen

    _dom_sub(dom, ug, "ug_video_info_id", str(ugm.ug_video_info_id))
    _dom_sub(dom, ug, "category_id", ugm.category_id)
    _dom_sub(dom, ug, "use_nfo", str(ugm.use_nfo))
    _dom_sub(dom, ug, "media_lib_set_id", str(ugm.media_lib_set_id))

    for g in ugm.genre:
        _dom_sub(dom, ug, "genre", g)

    if ugm.collection:
        col = dom.createElement("collection")
        _dom_sub(dom, col, "name", ugm.collection.name)
        if ugm.collection.tmdbid:
            _dom_sub(dom, col, "tmdbid", str(ugm.collection.tmdbid))
        ug.appendChild(col)

    for ph in ugm.play_history:
        el = dom.createElement("play_history")
        _dom_sub(dom, el, "uid", str(ph.uid))
        _dom_sub(dom, el, "progress", str(ph.progress))
        _dom_sub(dom, el, "current_play_time", str(ph.current_play_time))
        _dom_sub(dom, el, "last_access_time", str(ph.last_access_time))
        _dom_sub(dom, el, "watch_status", str(ph.watch_status))
        ug.appendChild(el)

    for fav in ugm.favorites:
        el = dom.createElement("favorites")
        _dom_sub(dom, el, "uid", str(fav.uid))
        _dom_sub(dom, el, "create_time", str(fav.create_time))
        _dom_sub(dom, el, "favorites_type", str(fav.favorites_type))
        ug.appendChild(el)

    if ugm.fileinfo:
        fi = dom.createElement("fileinfo")
        sd = dom.createElement("streamdetails")
        v = dom.createElement("video")
        _dom_sub(dom, v, "width", str(ugm.fileinfo.width))
        _dom_sub(dom, v, "height", str(ugm.fileinfo.height))
        _dom_sub(dom, v, "durationinseconds", str(ugm.fileinfo.duration))
        sd.appendChild(v)
        if ugm.fileinfo.codec:
            a = dom.createElement("audio")
            _dom_sub(dom, a, "codec", ugm.fileinfo.codec)
            _dom_sub(dom, a, "channels", str(ugm.fileinfo.channels))
            sd.appendChild(a)
        fi.appendChild(sd)
        ug.appendChild(fi)

    _dom_sub(dom, ug, "ctime", str(ugm.ctime))
    _dom_sub(dom, ug, "utime", str(ugm.utime))

    return ug


def _dom_sub(dom, parent, tag: str, text: str):
    """DOM 版 _sub：创建纯文子元素。空文本跳过。"""
    if not text and text != 0:
        return
    el = dom.createElement(tag)
    el.appendChild(dom.createTextNode(str(text)))
    parent.appendChild(el)
