"""通用工具函数 — 纯函数，无项目依赖"""

import datetime
import hashlib


# ---- 文件哈希 ----

def compute_file_hash(file_path: str) -> str:
    """计算文件内容的 SHA256 哈希。用于 strm 文件（绿联不会自动算）。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# ---- 分级转换 (int ↔ str) ----

_MPAA_INT_TO_STR = {1: "G", 2: "PG", 3: "PG-13", 4: "R", 5: "NC-17"}
_MPAA_STR_TO_INT = {
    "G": 1, "PG": 2, "PG-13": 3, "R": 4, "NC-17": 5,
    "TV-Y": 1, "TV-G": 1, "TV-PG": 2, "TV-14": 3, "TV-MA": 4,
}


def int_to_mpaa(grading: int) -> str:
    """分级数字 → 字符串。例: 3 → 'PG-13'"""
    return _MPAA_INT_TO_STR.get(grading, "")


def mpaa_to_int(mpaa: str) -> int:
    """分级字符串 → 数字。例: 'PG-13' → 3"""
    return _MPAA_STR_TO_INT.get(mpaa.upper(), 0)


# ---- 日期转换 (Unix 时间戳 ↔ 'YYYY-MM-DD') ----

def int_to_date_str(timestamp: int) -> str:
    """Unix 时间戳 → 'YYYY-MM-DD'"""
    if not timestamp or timestamp <= 0:
        return ""
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def date_str_to_int(date_str: str) -> int:
    """'YYYY-MM-DD' → Unix 时间戳"""
    if not date_str:
        return 0
    try:
        dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
        return int(dt.timestamp())
    except ValueError:
        return 0


# ---- 路径修正 ----

import os as _os

_IMAGE_FIELDS = ("poster_path", "backdrop_path", "logo_path",
                 "no_lang_poster_path", "no_lang_backdrop_path",
                 "last_play_file_path")


def fix_paths_for_video_dir(ug, video_dir: str):
    """当文件夹路径与 .ugreen.json 中的路径不一致时，修正图片和播放路径。
    仅处理本地绝对路径（/ 开头且不是 http），提取文件名拼接到当前目录，
    文件存在则更新，不存在保留旧值。
    """
    for attr in _IMAGE_FIELDS:
        old = getattr(ug, attr, None)
        if not old or not old.startswith("/") or old.startswith("http"):
            continue
        basename = _os.path.basename(old)
        new_path = _os.path.join(video_dir, basename)
        if new_path != old and _os.path.isfile(new_path):
            setattr(ug, attr, new_path)
