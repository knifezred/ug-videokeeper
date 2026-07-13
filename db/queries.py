"""数据库查询 — 纯 SELECT（不修改任何数据）"""
import psycopg2.extras
from typing import Iterator, Optional
from config import log
from models import DbRecord, FileRecord, VIDEO_INFO_COLUMNS, DB_DEFAULTS


# ---- 视频 ----

def fetch_video_by_category(conn, category_id: str) -> Optional[DbRecord]:
    """按 category_id 查询 ug_video_info 全部列（除自增主键 ug_video_info_id）"""
    sql = f"""
        SELECT {", ".join(VIDEO_INFO_COLUMNS)}
        FROM ug_video_info
        WHERE category_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return DbRecord(**{k: (v if v is not None else DB_DEFAULTS.get(k, "")) for k, v in row.items()})


# ---- 文件 ----

def fetch_all_file_info_cursor(conn, path_prefix: str = "",
                                batch_size: int = 500
                                ) -> Iterator[list[FileRecord]]:
    """服务端游标，分批返回 FileRecord。内存 O(batch_size) 而非 O(total)。"""
    sql = """
        SELECT
            f.file_id, f.file_name, f.file_path, f.folder_path,
            f.file_size, f.duration, f.season_num, f.episode_num,
            f.clarity, f.category_id::text AS category_id, f.media_lib_set_id, f.use_nfo,
            COALESCE(v.ug_video_info_id, 0) AS ug_video_info_id,
            COALESCE(v.name, '') AS video_name,
            COALESCE(v.type, 0) AS video_type,
            COALESCE(v.season, 0) AS video_season,
            COALESCE(v.ctime, 0) AS video_ctime,
            COALESCE(v.utime, 0) AS video_utime,
            v.collection_id AS video_collection_id,
            COALESCE((SELECT COUNT(*) FROM favorites WHERE once_id = f.category_id), 0) AS fav_count,
            GREATEST(
                COALESCE(v.ctime, 0),
                COALESCE(v.utime, 0),
                COALESCE(ph.max_play, 0),
                COALESCE(fv.max_fav, 0),
                COALESCE(c.utime, 0)
            ) AS max_mtime,
            MD5(
                COALESCE(v.name, '') || '|' ||
                COALESCE(v.release_date::text, '0') || '|' ||
                COALESCE(v.country_list::text, '{}') || '|' ||
                COALESCE(v.style_list::text, '{}') || '|' ||
                COALESCE(v.score::text, '0') || '|' ||
                COALESCE(v.introduction, '') || '|' ||
                COALESCE(v.poster_path, '') || '|' ||
                COALESCE(v.backdrop_path, '') || '|' ||
                COALESCE(v.logo_path, '')
            ) AS content_hash
        FROM file_info f
        LEFT JOIN ug_video_info v ON f.category_id = v.category_id
        LEFT JOIN (
            SELECT category_id, MAX(last_access_time) AS max_play
            FROM play_history GROUP BY category_id
        ) ph ON ph.category_id = f.category_id
        LEFT JOIN (
            SELECT once_id, MAX(create_time) AS max_fav
            FROM favorites GROUP BY once_id
        ) fv ON fv.once_id = f.category_id
        LEFT JOIN ug_collection c ON c.collection_id = v.collection_id
    """
    params = []
    if path_prefix:
        sql += " WHERE f.folder_path LIKE %s"
        params.append(path_prefix + "%")

    sql += " ORDER BY f.folder_path"

    with conn.cursor(name="sync_cursor",
                     cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            yield [FileRecord(**{
                k: (v if v is not None else _default_file(k))
                for k, v in row.items()
            }) for row in rows]


# ---- 演员 ----

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


# ---- 播放记录 ----

def fetch_play_history(conn, category_id: str) -> list[dict]:
    """JOIN file_info 获取每条播放记录对应的 file_name + hash_fingerprint + folder_path"""
    sql = """
        SELECT ph.uid, ph.category_id, ph.progress, ph.current_play_time,
               ph.last_access_time, ph.watch_status, ph.media_lib_set_id,
               ph.create_time, ph.iso_ts,
               f.file_name, f.hash_fingerprint, f.folder_path
        FROM play_history ph
        LEFT JOIN file_info f ON ph.file_id = f.file_id
        WHERE ph.category_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        return cur.fetchall()


# ---- 收藏 ----

def fetch_favorites(conn, category_id: str) -> list[dict]:
    sql = """
        SELECT uid, create_time, favorites_type
        FROM favorites
        WHERE once_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        return cur.fetchall()


# ---- 合集 ----

def fetch_collection(conn, category_id: str) -> Optional[dict]:
    """通过 ug_video_info.collection_id 查 ug_collection 全部字段"""
    sql_video = "SELECT collection_id FROM ug_video_info WHERE category_id = %s"
    with conn.cursor() as cur:
        cur.execute(sql_video, (category_id,))
        row = cur.fetchone()
    if not row or not row[0]:
        return None

    collection_id = row[0]
    sql_col = """
        SELECT name, collection_id, tmdb_id, pinyin_first, pinyin_full,
               poster_path, backdrop_path, language, introduction,
               is_manual_create, media_lib_set_id, year, score,
               category_id_list, ctime, utime, src_type, jp_name, cloud_id
        FROM ug_collection
        WHERE collection_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql_col, (collection_id,))
        return cur.fetchone()


# ---- 电视剧/剧集 ----

def fetch_episodes(conn, category_id: str) -> list[dict]:
    """查询某电视剧的所有剧集"""
    sql = """
        SELECT ug_television_episode_id, season, episode,
               name, overview, cover_path, language, episode_flag,
               ctime, utime, media_lib_set_id
        FROM ug_television_episode
        WHERE category_id = %s
        ORDER BY season, episode
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id,))
        return cur.fetchall()


def fetch_individual_episode(conn, category_id: str, season_num: int,
                              episode_num: int) -> Optional[dict]:
    """查询单集全部数据"""
    sql = """
        SELECT ug_television_episode_id, season, episode,
               name, overview, cover_path, language,
               ctime, utime, media_lib_set_id
        FROM ug_television_episode
        WHERE category_id = %s AND season = %s AND episode = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (category_id, season_num, episode_num))
        return cur.fetchone()


# ---- 字段默认值映射 ----

def _default(key: str):
    """RealDictCursor 返回的 None 值的默认值（派生自 DbRecord，单一来源）"""
    return DB_DEFAULTS.get(key, "")


def _default_file(key: str):
    """file_info 字段的默认值"""
    str_fields = {"file_name", "file_path", "folder_path", "category_id",
                  "video_name", "content_hash", "video_collection_id"}
    if key in str_fields:
        return ""
    return 0
