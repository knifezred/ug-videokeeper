"""NFO 文件读取 — 解析 XML 为 NfoRecord"""
import glob
import os
import xml.etree.ElementTree as ET
from typing import Optional
from config import log
from models import NfoRecord, VideoMeta, UgreenMeta, Actor, PlayHistory, Favorite, FileInfo


def read_nfo(nfo_path: str) -> Optional[NfoRecord]:
    """读取单个 NFO 文件，返回 NfoRecord；解析失败返回 None"""
    if not os.path.isfile(nfo_path):
        return None
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
    except ET.ParseError as e:
        log.warning("NFO 解析失败: %s — %s", nfo_path, e)
        return None

    nfo_type = _detect_type(root.tag)
    video_dir = os.path.dirname(nfo_path)
    official = VideoMeta()
    ugreen = UgreenMeta()
    present: set[str] = set()
    has_ugreen = root.find("ugreen") is not None

    _parse_official(root, official, present)
    _parse_ugreen(root, ugreen)

    if root.tag == "episodedetails":
        nfo_type = "episode"
    elif root.tag == "season":
        nfo_type = "season"

    return NfoRecord(
        nfo_type=nfo_type,
        nfo_path=nfo_path,
        video_dir=video_dir,
        official=official,
        ugreen=ugreen,
        has_ugreen=has_ugreen,
        official_fields_present=present,
    )


def find_nfo_in_dir(dir_path: str) -> Optional[str]:
    """在目录下查找任意 .nfo 文件，返回第一个匹配的路径。

    类型由 XML 根标签决定（movie/tvshow/season/episodedetails），
    不依赖文件名，因此比固定名称查找更健壮。
    单集 NFO（{视频文件名}.nfo）和标准命名的 NFO 都能被找到。
    """
    if not os.path.isdir(dir_path):
        return None
    files = glob.glob(os.path.join(dir_path, "*.nfo"))
    return files[0] if files else None


# ---- internal parse helpers ----

def _detect_type(tag: str) -> str:
    mapping = {"movie": "movie", "tvshow": "tvshow", "season": "season",
               "episodedetails": "episode"}
    clean = tag.split("}")[-1] if "}" in tag else tag
    return mapping.get(clean.lower().replace("{http", ""), "movie")


def _text(el, tag: str) -> Optional[str]:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _int_text(el, tag: str) -> Optional[int]:
    v = _text(el, tag)
    return int(v) if v else None


def _float_text(el, tag: str) -> Optional[float]:
    v = _text(el, tag)
    return float(v) if v else None


def _parse_official(root: ET.Element, meta: VideoMeta, present: set[str]):
    for tag in ["title", "year", "releasedate", "rating", "plot",
                "tmdbid", "doubanid", "mpaa", "season", "episode",
                "seasonnumber", "all_season_episode_num"]:
        if root.find(tag) is not None:
            present.add(tag)

    meta.title = _text(root, "title") or ""
    meta.year = _int_text(root, "year") or 0
    meta.releasedate = _text(root, "releasedate") or ""
    meta.rating = _float_text(root, "rating") or 0.0
    meta.plot = _text(root, "plot") or ""
    meta.tmdbid = _int_text(root, "tmdbid") or 0
    meta.doubanid = _int_text(root, "doubanid") or 0
    meta.mpaa = _text(root, "mpaa") or ""
    meta.season = _int_text(root, "season") or 0
    meta.episode = _int_text(root, "episode") or 0
    meta.seasonnumber = _int_text(root, "seasonnumber") or 0
    meta.all_season_episode_num = _int_text(root, "all_season_episode_num") or 0

    countries = [c.text.strip() for c in root.findall("country") if c.text]
    if countries:
        meta.country = countries
        present.add("country")

    genres = [g.text.strip() for g in root.findall("genre") if g.text]
    if genres:
        meta.genre = genres
        present.add("genre")

    actor_els = root.findall("actor")
    if actor_els:
        present.add("actor")
    for a_el in actor_els:
        meta.actors.append(Actor(
            name=_text(a_el, "name") or "",
            role=_text(a_el, "role") or "",
            tmdbid=_int_text(a_el, "tmdbid") or 0,
        ))


def _parse_ugreen(root: ET.Element, meta: UgreenMeta):
    ug = root.find("ugreen")
    if ug is None:
        return

    meta.ug_video_info_id = _int_text(ug, "ug_video_info_id") or 0
    meta.category_id = _text(ug, "category_id") or ""
    meta.use_nfo = _int_text(ug, "use_nfo") or 1
    meta.media_lib_set_id = _int_text(ug, "media_lib_set_id") or 0
    meta.ctime = _int_text(ug, "ctime") or 0
    meta.utime = _int_text(ug, "utime") or 0

    col_el = ug.find("collection")
    if col_el is not None:
        from models import Collection
        meta.collection = Collection(
            name=_text(col_el, "name") or "",
            tmdbid=_int_text(col_el, "tmdbid") or 0,
        )

    for ph_el in ug.findall("play_history"):
        meta.play_history.append(PlayHistory(
            uid=_int_text(ph_el, "uid") or 0,
            progress=_float_text(ph_el, "progress") or 0.0,
            current_play_time=_int_text(ph_el, "current_play_time") or 0,
            last_access_time=_int_text(ph_el, "last_access_time") or 0,
            watch_status=_int_text(ph_el, "watch_status") or 1,
        ))

    for fav_el in ug.findall("favorites"):
        meta.favorites.append(Favorite(
            uid=_int_text(fav_el, "uid") or 0,
            create_time=_int_text(fav_el, "create_time") or 0,
            favorites_type=_int_text(fav_el, "favorites_type") or 1,
        ))

    fi_el = ug.find("fileinfo")
    if fi_el is not None:
        stream = fi_el.find("streamdetails")
        if stream is not None:
            video = stream.find("video")
            audio = stream.find("audio")
            meta.fileinfo = FileInfo(
                width=_int_text(video, "width") or 0 if video is not None else 0,
                height=_int_text(video, "height") or 0 if video is not None else 0,
                duration=_int_text(video, "durationinseconds") or 0 if video is not None else 0,
                codec=_text(audio, "codec") or "" if audio is not None else "",
                channels=_int_text(audio, "channels") or 0 if audio is not None else 0,
            )
