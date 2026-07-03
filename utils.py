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
