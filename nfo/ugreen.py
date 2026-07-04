""".ugreen.json — 绿联扩展数据的 JSON 文件读写

替代 NFO <ugreen> 节点 + ugreen_tv.nfo 的自定义 XML 格式。
- 写入：全量覆写 json.dump
- 读取：json.load → UgreenRecord(**data)
"""

import json
import os
from dataclasses import asdict
from typing import Optional
from config import log
from models import UgreenRecord


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
        data.pop("genre", None)  # 旧 JSON 兼容：genre 已删除
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
    """将 UgreenRecord 序列化为 JSON dict（全量备份）"""
    d = asdict(record)
    # 清理空值集合
    if d.get("collection") is None:
        del d["collection"]
    if not d.get("episodes"):
        del d["episodes"]
    if d.get("nfo_snapshot") is None:
        del d["nfo_snapshot"]
    return d
