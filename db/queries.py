"""数据库查询与写入"""
import psycopg2.extras
from typing import Optional
from config import log
from models import (
    DbRecord, Actor, NfoRecord, FileRecord,
    PlayHistory, Favorite, FileInfo,
)


def fetch_video_by_category(conn, category_id: str) -> Optional[DbRecord]:
    """按 category_id 查询 ug_video_info（只 SELECT 同步所需列）"""
    sql = """
        SELECT ug_video_info_id, category_id, name, douban_id, tmdb_id,
               score, year, season, introduction,
               country_list, style_list, grading,
               release_date, all_season_episode_num,
               collection_id, ctime, utime
        FROM ug_video_info
        WHERE category_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return DbRecord(**{k: (v if v is not None else _default(k)) for k, v in row.items()})


def fetch_all_file_info(conn, path_prefix: str = "") -> list[FileRecord]:
    """查询 file_info 数据，JOIN ug_video_info 获取 ctime/utime。
    若 path_prefix 非空，仅返回 folder_path LIKE '{path_prefix}%' 的记录。
    """
    sql = """
        SELECT
            f.file_id, f.file_name, f.file_path, f.folder_path,
            f.file_size, f.duration, f.season_num, f.episode_num,
            f.clarity, f.category_id, f.media_lib_set_id, f.use_nfo,
            COALESCE(v.ug_video_info_id, 0) AS ug_video_info_id,
            COALESCE(v.name, '') AS video_name,
            COALESCE(v.type, 0) AS video_type,
            COALESCE(v.season, 0) AS video_season,
            COALESCE(v.ctime, 0) AS video_ctime,
            COALESCE(v.utime, 0) AS video_utime
        FROM file_info f
        LEFT JOIN ug_video_info v ON f.category_id = v.category_id
    """
    params = []
    if path_prefix:
        sql += " WHERE f.folder_path LIKE %s"
        params.append(path_prefix + "%")

    sql += " ORDER BY f.folder_path"

    records = []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            records.append(FileRecord(**{
                k: (v if v is not None else _default_file(k))
                for k, v in row.items()
            }))
    return records


def fetch_actors(conn, category_id: str) -> list[dict]:
    """查询演员，join ug_video_actor_relation + ug_actor"""
    sql = """
        SELECT r.role, r.actor_sequence, a.name, a.ug_actor_id, a.tmdb_id
        FROM ug_video_actor_relation r
        JOIN ug_actor a ON r.actor_once_id = a.actor_once_id
        WHERE r.category_id = %s
        ORDER BY r.actor_sequence
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        return cur.fetchall()


def fetch_play_history(conn, category_id: str) -> list[dict]:
    sql = """
        SELECT uid, progress, current_play_time, last_access_time, watch_status
        FROM play_history
        WHERE category_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        return cur.fetchall()


def fetch_favorites(conn, category_id: str) -> list[dict]:
    sql = """
        SELECT uid, create_time, favorites_type
        FROM favorites
        WHERE once_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        return cur.fetchall()


def fetch_collection(conn, category_id: str) -> Optional[dict]:
    """通过 ug_video_info.collection_id 查 ug_collection"""
    # 先取 video 的 collection_id
    sql_video = "SELECT collection_id FROM ug_video_info WHERE category_id = %s"
    with conn.cursor() as cur:
        cur.execute(sql_video, (category_id,))
        row = cur.fetchone()
    if not row or not row[0]:
        return None

    collection_id = row[0]
    sql_col = """
        SELECT name, tmdb_id
        FROM ug_collection
        WHERE collection_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql_col, (collection_id,))
        return cur.fetchone()


def fetch_episodes(conn, category_id: str) -> list[dict]:
    """查询某电视剧的所有剧集"""
    sql = """
        SELECT ug_television_episode_id, season, episode,
               name, overview, cover_path, language,
               ctime, utime, media_lib_set_id
        FROM ug_television_episode
        WHERE category_id = %s
        ORDER BY season, episode
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        return cur.fetchall()


# ---- write helpers ----

def _build_set_clause(data: dict) -> str:
    """只对有值的字段生成 SET 子句 ('col1 = %s, col2 = %s, ...')"""
    parts = [f"{k} = %s" for k in data if data[k] is not None]
    return ", ".join(parts)


def _build_set_values(data: dict) -> list:
    return [v for v in data.values() if v is not None]


def upsert_video_info(conn, nfo: NfoRecord) -> int:
    """
    将 NFO 官方字段写到 ug_video_info。
    已存在(按 category_id)则 UPDATE（只覆写 NFO 中声明了的字段），
    不存在则 INSERT。
    返回 ug_video_info_id。
    """
    fields = _build_video_fields(nfo)

    existing = fetch_video_by_category(conn, nfo.ugreen.category_id)

    if existing:
        # UPDATE — 只覆写 NFO 中明确声明的字段
        update_fields = {
            k: v for k, v in fields.items()
            if k in nfo.official_fields_present
        }
        if not update_fields:
            return existing.ug_video_info_id

        set_clause = _build_set_clause(update_fields)
        values = _build_set_values(update_fields) + [existing.category_id]
        sql = f"UPDATE ug_video_info SET {set_clause} WHERE category_id = %s"
        log.debug("UPDATE ug_video_info: %s", set_clause)
    else:
        # INSERT
        import time as _time
        fields.setdefault("category_id", nfo.ugreen.category_id)
        fields.setdefault("use_nfo", nfo.ugreen.use_nfo)
        fields.setdefault("media_lib_set_id", nfo.ugreen.media_lib_set_id)
        fields.setdefault("ctime", nfo.ugreen.ctime or 0)
        fields.setdefault("utime", int(_time.time()))
        columns = ", ".join(fields.keys())
        placeholders = ", ".join(["%s"] * len(fields))
        values = list(fields.values())
        sql = f"INSERT INTO ug_video_info ({columns}) VALUES ({placeholders}) RETURNING ug_video_info_id"
        log.debug("INSERT ug_video_info")

    with conn.cursor() as cur:
        cur.execute(sql, values)
        if not existing:
            new_id = cur.fetchone()[0]
            # 更新 NFO 的 ug_video_info_id
            nfo.ugreen.ug_video_info_id = new_id
            return new_id
        return existing.ug_video_info_id


def _build_video_fields(nfo: NfoRecord) -> dict:
    """从 NfoRecord 构建 ug_video_info 列字典，只包含有值的字段"""
    o = nfo.official
    present = nfo.official_fields_present
    fields = {}

    if "title" in present and o.title:
        fields["name"] = o.title
    if "year" in present and o.year:
        fields["year"] = o.year
    if "plot" in present and o.plot:
        fields["introduction"] = o.plot
    if "rating" in present and o.rating:
        fields["score"] = o.rating
    if "tmdbid" in present and o.tmdbid:
        fields["tmdb_id"] = o.tmdbid
    if "doubanid" in present and o.doubanid:
        fields["douban_id"] = o.doubanid
    if "mpaa" in present and o.mpaa:
        fields["grading"] = _parse_mpaa(o.mpaa)
    if "country" in present and o.country:
        fields["country_list"] = o.country
    if "genre" in present and o.genre:
        fields["style_list"] = o.genre
    if "season" in present or "seasonnumber" in present:
        fields["season"] = o.seasonnumber or o.season
    if "releasedate" in present and o.releasedate:
        fields["release_date"] = _parse_date_int(o.releasedate)
    if "all_season_episode_num" in present and o.all_season_episode_num:
        fields["all_season_episode_num"] = o.all_season_episode_num

    return fields


def sync_nfo_to_db(conn, nfo: NfoRecord, sync_utime: bool = False) -> int:
    """NFO → 数据库 完整回写（视频元数据 + 演员 + 播放记录 + 收藏 + 合集）。
    供 executor 和 watcher 共用，返回 ug_video_info_id。
    sync_utime=True 时将 NFO 文件 mtime 写入 DB.utime（规则 3.1b 手动编辑 NFO）。
    """
    import os as _os
    vid = upsert_video_info(conn, nfo)
    if sync_utime:
        mtime = int(_os.path.getmtime(nfo.nfo_path))
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ug_video_info SET utime = %s WHERE category_id = %s",
                (mtime, nfo.ugreen.category_id),
            )
    if nfo.official.actors:
        upsert_actors(conn, nfo.ugreen.category_id, nfo.official.actors)
    if nfo.ugreen.play_history:
        upsert_play_history(conn, nfo.ugreen.category_id, vid,
                            nfo.ugreen.play_history)
    if nfo.ugreen.favorites:
        upsert_favorites(conn, nfo.ugreen.category_id, nfo.ugreen.favorites)
    if nfo.ugreen.collection and nfo.ugreen.collection.name:
        upsert_collection_for_video(
            conn, nfo.ugreen.category_id,
            nfo.ugreen.collection.name,
            nfo.ugreen.collection.tmdbid,
        )
    return vid


def upsert_actors(conn, category_id: str, actors: list[Actor]):
    """删除旧演员关联，写入新的"""
    # 删除旧关联
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ug_video_actor_relation WHERE category_id = %s",
            (category_id,)
        )
    if not actors:
        return

    # 为每个 actor 确保 ug_actor 存在，拉取 actor_once_id
    values = []
    for seq, a in enumerate(actors):
        once_id = _ensure_actor(conn, a)
        values.append((category_id, a.role or "", once_id, seq))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO ug_video_actor_relation
               (category_id, role, actor_once_id, actor_sequence, media_lib_set_id)
               VALUES %s""",
            values,
        )


def _ensure_actor(conn, actor: Actor) -> str:
    """查找或创建 ug_actor，返回 actor_once_id"""
    # 尝试按 tmdb_id 查找
    if actor.tmdbid:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT actor_once_id FROM ug_actor WHERE tmdb_id = %s LIMIT 1",
                (actor.tmdbid,)
            )
            row = cur.fetchone()
            if row:
                return row[0]

    # 按名字查找
    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor_once_id FROM ug_actor WHERE name = %s LIMIT 1",
            (actor.name,)
        )
        row = cur.fetchone()
        if row:
            return row[0]

    # 都不存在则创建
    import uuid
    once_id = f"ug_actor_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ug_actor (actor_id, actor_once_id, name, tmdb_id, actor_data_source)
               VALUES (%s, %s, %s, %s, %s)""",
            (0, once_id, actor.name, actor.tmdbid or 0, 2),  # data_source=2 手动
        )
    return once_id


def upsert_play_history(conn, category_id: str, ug_video_info_id: int,
                        items: list[PlayHistory]):
    """按 uid + category_id 匹配，更新或插入播放记录"""
    for ph in items:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT play_history_id FROM play_history
                   WHERE category_id = %s AND uid = %s""",
                (category_id, ph.uid)
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """UPDATE play_history
                       SET ug_video_info_id = %s, progress = %s,
                           current_play_time = %s, last_access_time = %s,
                           watch_status = %s
                       WHERE category_id = %s AND uid = %s""",
                    (ug_video_info_id, ph.progress, ph.current_play_time,
                     ph.last_access_time, ph.watch_status,
                     category_id, ph.uid)
                )
            else:
                cur.execute(
                    """INSERT INTO play_history
                       (uid, category_id, ug_video_info_id, progress,
                        current_play_time, last_access_time, watch_status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (ph.uid, category_id, ug_video_info_id, ph.progress,
                     ph.current_play_time, ph.last_access_time, ph.watch_status)
                )


def upsert_favorites(conn, category_id: str, items: list[Favorite]):
    """按 uid + once_id(=category_id) 匹配"""
    for fav in items:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT favorites_id FROM favorites
                   WHERE once_id = %s AND uid = %s""",
                (category_id, fav.uid)
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """UPDATE favorites SET favorites_type = %s, create_time = %s
                       WHERE once_id = %s AND uid = %s""",
                    (fav.favorites_type, fav.create_time, category_id, fav.uid)
                )
            else:
                cur.execute(
                    """INSERT INTO favorites (uid, once_id, favorites_type, create_time)
                       VALUES (%s, %s, %s, %s)""",
                    (fav.uid, category_id, fav.favorites_type, fav.create_time)
                )


def upsert_collection_for_video(conn, category_id: str, collection_name: str,
                                 tmdbid: int = 0):
    """确保合集存在，并关联到视频"""
    if not collection_name:
        return

    # 查已有关联
    col_id = _find_or_create_collection(conn, collection_name, tmdbid)
    if col_id:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ug_video_info SET collection_id = %s WHERE category_id = %s",
                (col_id, category_id)
            )


def _find_or_create_collection(conn, name: str, tmdbid: int = 0) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT collection_id FROM ug_collection WHERE name = %s LIMIT 1",
            (name,)
        )
        row = cur.fetchone()
        if row:
            return row[0]

    import uuid
    col_id = f"ug_col_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ug_collection (name, collection_id, tmdb_id, language, is_manual_create)
               VALUES (%s, %s, %s, %s, %s)""",
            (name, col_id, str(tmdbid), "zh", True),
        )
    return col_id


# ---- helpers ----

def _default(key: str):
    """RealDictCursor 返回的 None 值的默认值"""
    return {
        "country_list": [], "style_list": [],
    }.get(key, 0 if "time" in key or "id" in key or "num" in key else "")


def _default_file(key: str):
    """file_info 字段的默认值"""
    str_fields = {"file_name", "file_path", "folder_path", "category_id",
                  "video_name"}
    if key in str_fields:
        return ""
    return 0


def _parse_date_int(date_str: str) -> int:
    """'1994-09-10' -> Unix 时间戳"""
    if not date_str:
        return 0
    import datetime
    try:
        dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
        return int(dt.timestamp())
    except ValueError:
        return 0


def _parse_mpaa(mpaa: str) -> int:
    """简单分级映射，非精确"""
    mapping = {"G": 1, "PG": 2, "PG-13": 3, "R": 4, "NC-17": 5,
               "TV-Y": 1, "TV-G": 1, "TV-PG": 2, "TV-14": 3, "TV-MA": 4}
    return mapping.get(mpaa.upper(), 0)
