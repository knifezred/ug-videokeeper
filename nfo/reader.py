"""NFO 文件读取 — 解析标准字段，不再解析 <ugreen>（数据来自 .ugreen.json）"""
import glob
import os
import re
import xml.etree.ElementTree as ET
from typing import Optional
from config import log
from models import NfoRecord, VideoMeta


def read_nfo(nfo_path: str) -> Optional[NfoRecord]:
    """读取单个 NFO 文件，返回官方字段；扩展数据需从 .ugreen.json 读取"""
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
    present: set[str] = set()

    _parse_official(root, official, present)

    log.debug("读取 NFO: %s type=%s title=%s fields=%d",
              nfo_path, nfo_type, official.title, len(present))

    return NfoRecord(
        nfo_type=nfo_type,
        nfo_path=nfo_path,
        video_dir=video_dir,
        official=official,
        official_fields_present=present,
    )


def find_nfo_in_dir(dir_path: str) -> Optional[str]:
    """在目录下查找 NFO：优先 <目录名>.nfo（避免误选 extras/sample），其次大小写不敏感回退。"""
    if not os.path.isdir(dir_path):
        return None
    # 优先精确匹配 <目录名>.nfo（标准命名）
    base = os.path.basename(os.path.normpath(dir_path))
    exact = os.path.join(dir_path, base + ".nfo")
    if os.path.isfile(exact):
        return exact
    # 大小写不敏感回退（Linux 下 .NFO 会被 glob("*.nfo") 漏掉）
    files = sorted(
        p for p in glob.glob(os.path.join(dir_path, "*.[nN][fF][oO]"))
        if os.path.isfile(p)
    )
    return files[0] if files else None


# ---- internal parse helpers ----

def _detect_type(tag: str) -> str:
    mapping = {"movie": "movie", "tvshow": "tvshow", "season": "season",
               "episodedetails": "episode"}
    clean = re.sub(r"\{[^}]*\}", "", tag)
    return mapping.get(clean.lower(), "movie")


def _text(el, tag: str) -> Optional[str]:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _int_text(el, tag: str) -> Optional[int]:
    v = _text(el, tag)
    if not v:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        log.warning("NFO 字段 %s 非整数: %r，忽略", tag, v)
        return None


def _float_text(el, tag: str) -> Optional[float]:
    v = _text(el, tag)
    if not v:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        log.warning("NFO 字段 %s 非数值: %r，忽略", tag, v)
        return None


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
