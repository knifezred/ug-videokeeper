"""通用工具函数 — 纯函数，无项目依赖"""

import calendar
import datetime
import hashlib
from config import log


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
    """Unix 时间戳 → 'YYYY-MM-DD'（统一 UTC，避免跨时区差一天）"""
    if not timestamp or timestamp <= 0:
        return ""
    return datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")


def date_str_to_int(date_str: str) -> int:
    """'YYYY-MM-DD' → Unix 时间戳（统一 UTC 零点，与 int_to_date_str 对称）"""
    if not date_str:
        return 0
    try:
        dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
        return int(calendar.timegm(dt.timetuple()))
    except ValueError:
        return 0


# ---- 路径修正 ----

import os as _os

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# 每个字段在新目录中搜索的文件名前缀
_IMG_SEARCH = {
    "poster_path":               ("poster", "folder", "cover"),
    "backdrop_path":             ("backdrop", "background", "fanart"),
    "logo_path":                 ("logo", "clearlogo"),
    "no_lang_poster_path":       ("poster", "folder", "cover"),
    "no_lang_backdrop_path":     ("backdrop", "background", "fanart"),
}


def _find_img_in_dir(video_dir: str, prefixes: tuple[str, ...]) -> str | None:
    """在 video_dir 根查找图片，优先精确前缀匹配，回退到包含匹配。"""
    try:
        entries = _os.listdir(video_dir)
    except OSError:
        return None

    def _match(mode):
        """mode='startswith' 优先；mode='in' 兜底"""
        for f in entries:
            f_lower = f.lower()
            if not f_lower.endswith(_IMG_EXTS):
                continue
            for p in prefixes:
                if mode == "startswith" and f_lower.startswith(p):
                    return _os.path.join(video_dir, f)
                if mode == "in" and p in f_lower:
                    return _os.path.join(video_dir, f)
        return None

    # 第一轮：精确前缀匹配（poster.jpg → yes, abc-poster.jpg → no）
    found = _match("startswith")
    if found:
        return found
    # 第二轮：包含匹配（abc-poster.jpg → yes）
    return _match("in")


def fix_paths_for_video_dir(ug, video_dir: str):
    """当目录移动后，修正图片路径到新目录。
    - 旧路径指向的目录与视频目录不一致 → 修正目录部分
    - 在新目录根搜索常见命名图片（poster.* / backdrop.* 等）
    - @appstore 路径不动
    """
    for attr in _IMG_SEARCH:
        old = getattr(ug, attr, None)
        log.debug("fix_paths: %s = %r", attr, old)

        # 有值但不是 / 开头 → 跳过（如 http / 相对路径）
        # 空值/None 则继续走搜索，看目录下有没有图
        if old and not old.startswith("/"):
            log.debug("fix_paths:   → 跳过（非 / 开头）")
            continue

        # 绿联托管路径 → 不动（不随文件夹搬移）
        if old and "@appstore/com.ugreen.videomgr" in old:
            log.debug("fix_paths:   → 跳过（@appstore 管理路径）")
            continue

        # 第一步：旧路径目录与视频目录不一致 → 修正目录部分
        if old:
            old_dir = _os.path.dirname(old)
            if old_dir != video_dir:
                corrected = _os.path.join(video_dir, _os.path.basename(old))
                log.debug("fix_paths:   → 目录不一致 %r → %r", old, corrected)
                setattr(ug, attr, corrected)
                old = corrected  # 让接下来的搜索继续基于修正后的路径

        # 第二步：在新目录搜索对应前缀的图片（比目录修正更精准）
        new_path = _find_img_in_dir(video_dir, _IMG_SEARCH[attr])
        if new_path and new_path != old:
            log.debug("fix_paths:   → 搜索命中，更新为 %s", new_path)
            setattr(ug, attr, new_path)
        elif new_path:
            log.debug("fix_paths:   → 搜索命中，与当前路径相同")
        else:
            log.debug("fix_paths:   → 新目录未找到匹配图片")
