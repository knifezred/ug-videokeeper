"""
一致性检查 — 启动时自动校验模型/序列化/查询的表字段对齐。
不依赖数据库连接，只在 import 时静态检查。
"""
import sys


def _check_ugreen_record_consistency():
    from models import UgreenRecord, DbRecord
    from nfo.ugreen import _to_dict

    # 1. 检查 UgreenRecord 是否有重复字段名
    field_names = list(UgreenRecord.__dataclass_fields__.keys())
    dupes = [f for f in field_names if field_names.count(f) > 1]
    if dupes:
        raise SyntaxError(
            f"UgreenRecord 重复字段: {set(dupes)}\n"
            f"请删除重复声明"
        )
    ur_fields = set(field_names)

    # 2. 检查 _to_dict 是否有重复 JSON key
    dummy = _build_dummy_urecord()
    d = _to_dict(dummy)
    json_keys = list(d.keys())
    dupes2 = [k for k in json_keys if json_keys.count(k) > 1]
    if dupes2:
        raise SyntaxError(
            f"_to_dict 输出重复 JSON key: {set(dupes2)}"
        )

    # 3. 检查 UgreenRecord 所有字段都出现在 _to_dict 中
    obj_fields = {"play_history", "favorites", "collection", "episodes", "nfo_snapshot"}
    missing_keys = {f for f in ur_fields if f not in obj_fields and f not in json_keys}
    if missing_keys:
        raise SyntaxError(f"UgreenRecord 字段在 _to_dict 中遗漏: {missing_keys}")

    # 4. 检查 _to_dict 输出的键是否都是 UgreenRecord 字段
    extra_keys = set(json_keys) - ur_fields - {"version"}
    if extra_keys:
        raise SyntaxError(f"_to_dict 输出多余的键（非 UgreenRecord 字段）: {extra_keys}")

    # 5. 检查 DbRecord ⊆ UgreenRecord
    db_fields = set(DbRecord.__dataclass_fields__.keys())
    extra_db = db_fields - ur_fields - {"ug_video_info_id"}
    if extra_db:
        raise SyntaxError(f"DbRecord 含 UgreenRecord 没有的字段: {extra_db}")

    print("[check] UgreenRecord 一致性检查通过", file=sys.stderr)


def _check_read_ugreen_roundtrip():
    """写入 → 读取 → 验证不崩"""
    from models import UgreenRecord
    from nfo.ugreen import _to_dict
    dummy = _build_dummy_urecord()
    d = _to_dict(dummy)
    try:
        record = UgreenRecord(**d)
    except TypeError as e:
        raise SyntaxError(
            f"read_ugreen 模拟失败: {e}\n"
            f"_to_dict JSON keys: {sorted(d.keys())}\n"
            f"UgreenRecord fields: {sorted(UgreenRecord.__dataclass_fields__.keys())}"
        )
    print("[check] read_ugreen 往返检查通过", file=sys.stderr)


def _check_all_can_import():
    modules = [
        "config", "models", "utils", "state",
        "nfo.ugreen", "nfo.reader", "nfo.writer",
        "sync.strategy",
    ]
    for m in modules:
        try:
            __import__(m)
        except Exception as e:
            raise SyntaxError(f"import {m} 失败: {e}")
    print("[check] 全部 import 通过", file=sys.stderr)


def _build_dummy_urecord():
    from models import UgreenRecord
    return UgreenRecord(
        category_id="test", ug_video_info_id=1, media_lib_set_id=18,
        ctime=100, utime=100,
        name="test", pinyin_first="", pinyin_full="", to9_digit="",
        year=2024, season=0, introduction="", score=0.0,
        douban_id=0, tmdb_id=0, style_list=[], grading=0,
        release_date=0, last_release_date=0, all_season_episode_num=0,
        country_list=[], type=1, use_nfo=1,
        poster_path="", backdrop_path="", logo_path="", tagline="",
        no_lang_poster_path="", no_lang_backdrop_path="",
        language="", old_category_id="", collection_id="",
        collection_time=0, last_play_file_path="", jp_name="",
        ug_media_id="",
        play_history=[], favorites=[], collection=None,
        episodes=[],
    )


def run_all():
    _check_ugreen_record_consistency()
    _check_read_ugreen_roundtrip()
    _check_all_can_import()
    print("[check] 全部检查通过", file=sys.stderr)
