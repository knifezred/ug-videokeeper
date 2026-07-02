"""数据库查询与写入"""
import os
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
               collection_id, media_lib_set_id, ctime, utime
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
            f.clarity, f.category_id::text AS category_id, f.media_lib_set_id, f.use_nfo,
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
    """JOIN file_info 获取每条播放记录对应的 file_name + hash_fingerprint + folder_path。
    strm 场景下 hash_fingerprint 为空，由调用方（write_nfo_from_db）按需补算。"""
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
        # UPDATE — 覆写 NFO 中声明的字段 + ugreen 衍生字段
        update_fields = {
            k: v for k, v in fields.items()
            if k in nfo.official_fields_present or k == "style_list"
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
            nfo.ugreen.ug_video_info_id = new_id
            log.debug("INSERT ug_video_info: cat=%s new_id=%d", nfo.ugreen.category_id, new_id)
            return new_id
        log.debug("UPDATE ug_video_info: cat=%s id=%d", nfo.ugreen.category_id, existing.ug_video_info_id)
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
    genre = _to_style_list(nfo)
    if genre:
        fields["style_list"] = genre
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

    # 先解析最新 category_id（目录移动后 NFO 里的值已过期）
    resolved_cat = _resolve_category_id(conn, nfo.video_dir,
                                        os.path.basename(nfo.nfo_path))
    if resolved_cat:
        nfo.ugreen.category_id = resolved_cat

    vid = upsert_video_info(conn, nfo)
    if sync_utime:
        mtime = int(_os.path.getmtime(nfo.nfo_path))
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ug_video_info SET utime = %s WHERE category_id = %s",
                (mtime, nfo.ugreen.category_id),
            )
        log.debug("sync_utime: cat=%s utime=%d", nfo.ugreen.category_id, mtime)

    if nfo.ugreen.play_history:
        log.debug("sync_nfo_to_db: 写入 %d 条播放记录",
                  len(nfo.ugreen.play_history))
        upsert_play_history(conn, nfo.ugreen.play_history,
                            nfo.video_dir, os.path.basename(nfo.nfo_path))
    if nfo.ugreen.favorites:
        log.debug("sync_nfo_to_db: 写入 %d 条收藏 cat=%s",
                  len(nfo.ugreen.favorites), nfo.ugreen.category_id)
        upsert_favorites(conn, nfo.ugreen.category_id, nfo.ugreen.favorites)
    if nfo.ugreen.collection and nfo.ugreen.collection.name:
        log.debug("sync_nfo_to_db: 写入合集 %s cat=%s",
                  nfo.ugreen.collection.name, nfo.ugreen.category_id)
        upsert_collection_for_video(conn, nfo.ugreen.category_id,
                                    nfo.ugreen.collection)
    return vid


def upsert_actors(conn, category_id: str, actors: list[Actor],
                  media_lib_set_id: int = 0):
    """删除旧演员关联，写入新的"""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ug_video_actor_relation WHERE category_id = %s",
            (category_id,),
        )
    if not actors:
        log.debug("upsert_actors: 无演员, cat=%s", category_id)
        return

    once_ids = _ensure_actors_batch(conn, actors)
    values = [(category_id, a.role or "", oid, seq, media_lib_set_id)
              for seq, (a, oid) in enumerate(zip(actors, once_ids))]

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO ug_video_actor_relation
               (category_id, role, actor_once_id, actor_sequence, media_lib_set_id)
               VALUES %s""",
            values,
        )
    log.debug("upsert_actors: 写入 %d 个演员关联 cat=%s", len(values), category_id)


def _ensure_actors_batch(conn, actors: list[Actor]) -> list[str]:
    """批量查找或创建 ug_actor，返回 actor_once_id 列表（顺序与输入一致）"""
    if not actors:
        return []

    tmdb_ids = [a.tmdbid for a in actors if a.tmdbid]
    names = [a.name for a in actors]

    tmdb_map: dict[int, str] = {}
    if tmdb_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tmdb_id, actor_once_id FROM ug_actor WHERE tmdb_id = ANY(%s)",
                (tmdb_ids,),
            )
            for row in cur.fetchall():
                tmdb_map[row[0]] = row[1]

    name_map: dict[str, str] = {}
    if names:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, actor_once_id FROM ug_actor WHERE name = ANY(%s)",
                (names,),
            )
            for row in cur.fetchall():
                name_map[row[0]] = row[1]

    results: list[str] = []
    to_insert: list[tuple] = []

    import uuid as _uuid
    for a in actors:
        if a.tmdbid and a.tmdbid in tmdb_map:
            results.append(tmdb_map[a.tmdbid])
        elif a.name in name_map:
            results.append(name_map[a.name])
        else:
            once_id = f"ug_actor_{_uuid.uuid4().hex[:8]}"
            results.append(once_id)
            to_insert.append((0, once_id, a.name, a.tmdbid or 0, 2))

    if to_insert:
        log.debug("_ensure_actors_batch: 创建 %d 个新演员", len(to_insert))
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO ug_actor (actor_id, actor_once_id, name, tmdb_id, actor_data_source)
                   VALUES %s""",
                to_insert,
            )

    return results


def upsert_play_history(conn, items: list[PlayHistory],
                        video_dir: str, nfo_filename: str):
    """三级匹配定位 file_info：hash_fingerprint → file_name+folder → folder+prefix。
    每条播放记录独立匹配，匹配到则写入对应 file_id，否则跳过。
    """
    if not items:
        return

    nfo_prefix = os.path.splitext(nfo_filename)[0].lower() if nfo_filename else ""

    # 一次性查询所有可能的 file_info 候选
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # 候选集：folder_path 匹配的所有 file_info
        cur.execute(
            """SELECT f.file_id, f.category_id, f.file_name, f.folder_path,
                      f.hash_fingerprint,
                      COALESCE(v.ug_video_info_id, 0) AS vid
               FROM file_info f
               LEFT JOIN ug_video_info v ON f.category_id = v.category_id
               WHERE f.folder_path = %s""",
            (video_dir,),
        )
        candidates = cur.fetchall()

    if not candidates:
        log.warning("upsert_play_history: folder=%s 未匹配到 file_info",
                    video_dir)
        return

    # 逐条匹配
    matched = []  # (play_history, file_id, category_id, ug_video_info_id)
    for ph in items:
        row = _match_file_info(ph, candidates, nfo_prefix)
        if row:
            matched.append((ph, row["file_id"], row["category_id"], row["vid"]))
        else:
            log.warning("upsert_play_history: ph uid=%s hash=%s → 未匹配",
                        ph.uid, ph.hash_fingerprint[:8] if ph.hash_fingerprint else "")

    if not matched:
        return

    # 分组写库（按 category_id + uid 匹配）
    by_cat: dict[str, list] = {}
    for ph, fid, cat, vid in matched:
        by_cat.setdefault(cat, []).append((ph, fid, vid))

    with conn.cursor() as cur:
        for cat, group in by_cat.items():
            uids = [ph.uid for ph, _, _ in group]
            cur.execute(
                "SELECT uid FROM play_history WHERE category_id = %s AND uid = ANY(%s)",
                (cat, uids),
            )
            existing = {r[0] for r in cur.fetchall()}

            for ph, fid, vid in group:
                if ph.uid in existing:
                    cur.execute(
                        """UPDATE play_history
                           SET ug_video_info_id = %s, file_id = %s,
                               media_lib_set_id = %s, progress = %s,
                               current_play_time = %s, last_access_time = %s,
                               watch_status = %s, create_time = %s,
                               iso_ts = %s
                           WHERE category_id = %s AND uid = %s""",
                        (vid, fid, ph.media_lib_set_id, ph.progress,
                         ph.current_play_time, ph.last_access_time,
                         ph.watch_status, ph.create_time, ph.iso_ts,
                         cat, ph.uid),
                    )
                else:
                    cur.execute(
                        """INSERT INTO play_history
                           (uid, category_id, ug_video_info_id, file_id,
                            media_lib_set_id, progress, current_play_time,
                            last_access_time, watch_status, create_time,
                            iso_ts)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                   %s, %s)""",
                        (ph.uid, cat, vid, fid, ph.media_lib_set_id, ph.progress,
                         ph.current_play_time, ph.last_access_time,
                         ph.watch_status, ph.create_time, ph.iso_ts),
                    )
    log.info("upsert_play_history: 写入 %d/%d 条", len(matched), len(items))


def _match_file_info(ph: PlayHistory, candidates: list[dict], nfo_prefix: str) -> dict | None:
    """二级匹配：hash_fingerprint (含 strm 自算) → folder+prefix 兜底"""
    # 1. hash_fingerprint 优先
    # 1a. 普通文件：DB 已有 hash_fingerprint → 直接比对
    if ph.hash_fingerprint:
        for c in candidates:
            if c["hash_fingerprint"] and c["hash_fingerprint"] == ph.hash_fingerprint:
                log.debug("  ph uid=%s 命中 hash_fingerprint → file_id=%d",
                          ph.uid, c["file_id"])
                return c
        # 1b. strm 文件：DB hash_fingerprint 为空，NFO 端自己算过 hash
        #      重新计算 strm 文件 hash 跟 NFO 存的比对
        for c in candidates:
            if not c["hash_fingerprint"] and c["file_name"].endswith(".strm"):
                strm_path = os.path.join(c["folder_path"], c["file_name"])
                if os.path.isfile(strm_path):
                    try:
                        cur_hash = _compute_file_hash(strm_path)
                    except OSError as e:
                        log.warning("strm hash 计算失败 %s: %s", strm_path, e)
                        continue
                    if cur_hash == ph.hash_fingerprint:
                        log.debug("  ph uid=%s 命中 strm hash → file_id=%d",
                                  ph.uid, c["file_id"])
                        return c

    # 2. NFO 所在目录 + nfo prefix（hash 失败时的兜底）
    if nfo_prefix:
        for c in candidates:
            if c["file_name"].lower().startswith(nfo_prefix):
                log.debug("  ph uid=%s 命中 folder+prefix → file_id=%d",
                          ph.uid, c["file_id"])
                return c

    return None


def upsert_favorites(conn, category_id: str, items: list[Favorite]):
    """按 uid + once_id 批量匹配"""
    if not items:
        return
    uids = [fav.uid for fav in items]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT uid FROM favorites WHERE once_id = %s AND uid = ANY(%s)",
            (category_id, uids),
        )
        existing = {row[0] for row in cur.fetchall()}

    updates = [fav for fav in items if fav.uid in existing]
    inserts = [fav for fav in items if fav.uid not in existing]

    log.debug("upsert_favorites: cat=%s updates=%d inserts=%d",
              category_id, len(updates), len(inserts))

    if updates:
        with conn.cursor() as cur:
            cur.executemany(
                """UPDATE favorites SET favorites_type = %(ft)s, create_time = %(ct)s
                   WHERE once_id = %(once)s AND uid = %(uid)s""",
                [{"ft": fav.favorites_type, "ct": fav.create_time,
                  "once": category_id, "uid": fav.uid}
                 for fav in updates],
            )

    if inserts:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO favorites (uid, once_id, favorites_type, create_time)
                   VALUES %s""",
                [(fav.uid, category_id, fav.favorites_type, fav.create_time)
                 for fav in inserts],
            )


def upsert_collection_for_video(conn, category_id: str, col: "Collection"):
    """确保合集存在（按 collection_id > name 匹配），写入全部字段，关联到视频"""
    if not col.name:
        return

    col_id = _find_or_create_collection(conn, col)
    if col_id:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ug_video_info SET collection_id = %s WHERE category_id = %s",
                (col_id, category_id)
            )


def _find_or_create_collection(conn, col: "Collection") -> Optional[str]:
    """按 collection_id 精确匹配，其次按 name 匹配；存在则 UPDATE，不存在则 INSERT"""
    from models import Collection

    with conn.cursor() as cur:
        # 1. 精确匹配 collection_id
        if col.collection_id:
            cur.execute(
                "SELECT collection_id FROM ug_collection WHERE collection_id = %s",
                (col.collection_id,),
            )
            row = cur.fetchone()
            if row:
                _update_collection(conn, col)
                return row[0]

        # 2. 按 name 匹配
        cur.execute(
            "SELECT collection_id FROM ug_collection WHERE name = %s LIMIT 1",
            (col.name,),
        )
        row = cur.fetchone()
        if row:
            _update_collection(conn, col)
            return row[0]

    # 3. 新建
    import uuid
    col_id = col.collection_id or f"ug_col_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ug_collection
               (name, collection_id, tmdb_id, pinyin_first, pinyin_full,
                poster_path, backdrop_path, language, introduction,
                is_manual_create, media_lib_set_id, year, score,
                category_id_list, ctime, utime, src_type, jp_name, cloud_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (col.name, col_id, str(col.tmdb_id), col.pinyin_first, col.pinyin_full,
             col.poster_path, col.backdrop_path, col.language, col.introduction,
             col.is_manual_create, col.media_lib_set_id, col.year, col.score,
             col.category_id_list, col.ctime, col.utime, col.src_type, col.jp_name,
             col.cloud_id),
        )
    return col_id


def _update_collection(conn, col: "Collection"):
    """更新已存在合集的全部字段"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ug_collection SET
                 name = %s, tmdb_id = %s, pinyin_first = %s, pinyin_full = %s,
                 poster_path = %s, backdrop_path = %s, language = %s,
                 introduction = %s, is_manual_create = %s,
                 media_lib_set_id = %s, year = %s, score = %s,
                 category_id_list = %s, ctime = %s, utime = %s,
                 src_type = %s, jp_name = %s, cloud_id = %s
               WHERE collection_id = %s""",
            (col.name, str(col.tmdb_id), col.pinyin_first, col.pinyin_full,
             col.poster_path, col.backdrop_path, col.language, col.introduction,
             col.is_manual_create, col.media_lib_set_id, col.year, col.score,
             col.category_id_list, col.ctime, col.utime, col.src_type, col.jp_name,
             col.cloud_id, col.collection_id),
        )


# ---- helpers ----

def _resolve_category_id(conn, video_dir: str, nfo_filename: str) -> str:
    """通过 folder_path + NFO 文件名前缀定位 file_info，获取当前正确的 category_id。
    目录移动后 NFO 里存的 category_id 已过期，此函数返回 DB 当前真实值。
    返回空字符串表示未找到。"""
    nfo_prefix = os.path.splitext(nfo_filename)[0].lower()
    with conn.cursor() as cur:
        if nfo_prefix:
            cur.execute(
                "SELECT category_id FROM file_info "
                "WHERE folder_path = %s AND LOWER(file_name) LIKE %s LIMIT 1",
                (video_dir, nfo_prefix + "%"),
            )
        else:
            cur.execute(
                "SELECT category_id FROM file_info WHERE folder_path = %s LIMIT 1",
                (video_dir,),
            )
        row = cur.fetchone()
    cat = row[0] if row else ""
    if cat:
        log.debug("_resolve_category_id: dir=%s nfo=%s → %s", video_dir, nfo_filename, cat)
    else:
        log.warning("_resolve_category_id: dir=%s nfo=%s → 未找到", video_dir, nfo_filename)
    return cat


def _compute_file_hash(file_path: str) -> str:
    """计算文件内容的 SHA256 哈希。用于 strm 文件（绿联不会自动算）。"""
    import hashlib
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _to_style_list(nfo: NfoRecord) -> list[int]:
    """将 ugreen genre 转为 int 列表（适配 integer[] 列），回退到 official genre"""
    ug_genre = nfo.ugreen.genre
    if ug_genre:
        return [int(g) for g in ug_genre if g.isdigit()]
    if "genre" in nfo.official_fields_present and nfo.official.genre:
        return [int(g) for g in nfo.official.genre if g.isdigit()]
    return []


# 字段 → 空值默认映射（仅 fetch_video_by_category 返回的列）
_DB_DEFAULTS: dict[str, int | str | float | list] = {
    "ug_video_info_id": 0, "category_id": "", "name": "",
    "douban_id": 0, "tmdb_id": 0,
    "score": 0.0, "year": 0, "season": 0,
    "introduction": "", "country_list": [], "style_list": [],
    "grading": 0, "release_date": 0,
    "all_season_episode_num": 0,
    "collection_id": "", "media_lib_set_id": 0, "ctime": 0, "utime": 0,
}


def _default(key: str):
    """RealDictCursor 返回的 None 值的默认值（显式映射，无启发式陷阱）"""
    return _DB_DEFAULTS.get(key, "")


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
