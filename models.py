"""数据模型 — 对应数据库表与 NFO 结构"""
from dataclasses import dataclass, field, fields as dc_fields, MISSING
from typing import Optional


@dataclass
class Actor:
    name: str
    role: str = ""
    tmdbid: int = 0


@dataclass
class Collection:
    """ug_collection 完整字段（除 ug_collection_id 自增）"""
    name: str = ""
    collection_id: str = ""
    tmdb_id: str = "0"
    pinyin_first: str = ""
    pinyin_full: str = ""
    poster_path: str = ""
    backdrop_path: str = ""
    language: str = ""
    introduction: str = ""
    is_manual_create: bool = False
    media_lib_set_id: int = 0
    year: int = 0
    score: float = 0.0
    category_id_list: list[str] = field(default_factory=list)
    src_type: int = 0
    jp_name: str = ""
    cloud_id: str = ""
    ctime: int = 0
    utime: int = 0


@dataclass
class PlayHistory:
    uid: int
    category_id: str = ""       # NFO 存储用；恢复时用 hash_fingerprint 实时查
    hash_fingerprint: str = ""  # 普通文件来自 DB，strm 客户端自算
    progress: float = 0.0
    current_play_time: int = 0
    last_access_time: int = 0
    watch_status: int = 1
    media_lib_set_id: int = 0
    create_time: int = 0
    iso_ts: str = ""


@dataclass
class Favorite:
    uid: int
    create_time: int = 0
    favorites_type: int = 1


@dataclass
class FileInfo:
    width: int = 0
    height: int = 0
    duration: int = 0
    codec: str = ""
    channels: int = 0


@dataclass
class UgreenRecord:
    """.ugreen.json 完整数据 — ug_video_info 全部非主键字段 + 扩展数据"""
    version: int = 1

    # 同步决策字段
    category_id: str = ""
    ug_video_info_id: int = 0
    media_lib_set_id: int = 0
    ctime: int = 0
    utime: int = 0

    # ug_video_info 全部字段（除 ug_video_info_id 自增主键）
    name: str = ""
    pinyin_first: str = ""
    pinyin_full: str = ""
    to9_digit: str = ""
    year: int = 0
    season: int = 0
    introduction: str = ""
    score: float = 0.0
    douban_id: int = 0
    tmdb_id: int = 0
    style_list: list[int] = field(default_factory=list)
    grading: int = 0
    release_date: int = 0
    last_release_date: int = 0
    all_season_episode_num: int = 0
    country_list: list[int] = field(default_factory=list)
    type: int = 0
    use_nfo: int = 1
    poster_path: str = ""
    backdrop_path: str = ""
    logo_path: str = ""
    tagline: str = ""
    no_lang_poster_path: str = ""
    no_lang_backdrop_path: str = ""
    language: str = ""
    old_category_id: str = ""
    collection_id: str = ""
    collection_time: int = 0
    last_play_file_path: str = ""
    jp_name: str = ""
    ug_media_id: str = ""

    # 绿联扩展（来自 play_history / favorites / ug_collection）
    play_history: list[PlayHistory] = field(default_factory=list)
    favorites: list[Favorite] = field(default_factory=list)
    collection: Optional[Collection] = None
    actors: list[Actor] = field(default_factory=list)  # 演员关系（备份/恢复）

    # NFO 字段快照，用于 Watchdog 逐字段 diff
    nfo_snapshot: Optional[dict] = None

    # 电视剧专用
    episodes: list[dict] = field(default_factory=list)

    def __post_init__(self):
        """反序列化时恢复嵌套对象"""
        if self.play_history and isinstance(self.play_history[0], dict):
            self.play_history = [PlayHistory(**ph) for ph in self.play_history]
        if self.favorites and isinstance(self.favorites[0], dict):
            self.favorites = [Favorite(**fv) for fv in self.favorites]
        if isinstance(self.collection, dict):
            self.collection = Collection(**self.collection)
        if self.actors and isinstance(self.actors[0], dict):
            self.actors = [Actor(name=a.get("name", ""), role=a.get("role", ""),
                                 tmdbid=a.get("tmdbid", a.get("tmdb_id", 0)))
                           for a in self.actors]


@dataclass
class VideoMeta:
    """视频元数据 — 对应 ug_video_info 表 + NFO 官方字段"""
    title: str = ""
    year: int = 0
    releasedate: str = ""
    rating: float = 0.0
    plot: str = ""
    tmdbid: int = 0
    doubanid: int = 0
    country: list[str] = field(default_factory=list)
    genre: list[str] = field(default_factory=list)
    mpaa: str = ""
    actors: list[Actor] = field(default_factory=list)
    # 电视剧专用
    season: int = 0
    episode: int = 0
    seasonnumber: int = 0
    all_season_episode_num: int = 0


@dataclass
class NfoRecord:
    """一个完整的 NFO 文件解析结果"""
    nfo_type: str = ""           # "movie" | "tvshow" | "season" | "episode"
    nfo_path: str = ""
    video_dir: str = ""
    category_id: str = ""        # 由 resolve_category_id 设置
    ug_video_info_id: int = 0
    official: VideoMeta = field(default_factory=VideoMeta)
    # 记录 NFO 中实际出现了哪些官方字段（用于精确覆写）
    official_fields_present: set[str] = field(default_factory=set)


@dataclass
class DbRecord:
    """数据库查询结果 — ug_video_info 行（全字段）"""
    ug_video_info_id: int = 0
    category_id: str = ""
    name: str = ""
    pinyin_first: str = ""
    pinyin_full: str = ""
    to9_digit: str = ""
    year: int = 0
    season: int = 0
    introduction: str = ""
    score: float = 0.0
    douban_id: int = 0
    tmdb_id: int = 0
    style_list: list[int] = field(default_factory=list)
    grading: int = 0
    release_date: int = 0
    last_release_date: int = 0
    all_season_episode_num: int = 0
    country_list: list[int] = field(default_factory=list)
    type: int = 0
    poster_path: str = ""
    backdrop_path: str = ""
    logo_path: str = ""
    tagline: str = ""
    no_lang_poster_path: str = ""
    no_lang_backdrop_path: str = ""
    language: str = ""
    old_category_id: str = ""
    collection_id: str = ""
    collection_time: int = 0
    media_lib_set_id: int = 0
    last_play_file_path: str = ""
    jp_name: str = ""
    ug_media_id: str = ""
    use_nfo: int = 1
    ctime: int = 0
    utime: int = 0


# ---- ug_video_info 字段单一权威来源 ----
# DbRecord 是 ug_video_info 查询结果的容器，其字段即表的列。
# 以下派生量全部以 DbRecord 为准：新增/删除列只需改 DbRecord 一处。
# 查询列（不含 use_nfo：该字段由其他写入路径管理，不参与此 SELECT）
VIDEO_INFO_COLUMNS: tuple[str, ...] = tuple(
    f.name for f in dc_fields(DbRecord) if f.name != "use_nfo"
)


def _build_db_defaults() -> dict:
    """由 DbRecord 字段默认值自动生成 NULL 兜底映射，杜绝手写漂移"""
    d: dict = {}
    for f in dc_fields(DbRecord):
        if f.default is not MISSING:
            d[f.name] = f.default
        elif f.default_factory is not MISSING:  # noqa: E721
            d[f.name] = f.default_factory()
        else:
            d[f.name] = ""
    return d


DB_DEFAULTS: dict = _build_db_defaults()


# 用户在 NAS UI 可直接编辑、且从 .ugreen.json 恢复时必须还原的字段。
# 其余 ug_video_info 字段（year / tmdb_id / douban_id / grading / type 等）
# 仅写入 .ugreen.json 做备份，恢复时不回写——
# 避免用旧备份覆盖 DB 中由刮削器刷新的新值。
USER_EDITABLE_FIELDS: frozenset[str] = frozenset({
    "name", "introduction", "score",
    "release_date", "country_list", "style_list",
    "poster_path", "backdrop_path", "logo_path",
    "ctime", "utime",
})


@dataclass
class SyncResult:
    """单次同步结果"""
    nfo_path: str = ""
    direction: str = ""          # "nfo_to_db" | "db_to_nfo" | "skip" | "error"
    scene: str = ""              # "1"|"2"|"3.1"|"3.2"|"3.3" 等
    message: str = ""
    synced: bool = True          # False = 未实际执行同步，调用方跳过写缓存


@dataclass
class FileRecord:
    """file_info 行 + 关联的 ug_video_info 核心字段"""
    file_id: int = 0
    file_name: str = ""
    file_path: str = ""
    folder_path: str = ""
    file_size: int = 0
    duration: int = 0
    season_num: int = 0
    episode_num: int = 0
    clarity: int = 0
    category_id: str = ""
    media_lib_set_id: int = 0
    use_nfo: int = 1
    # 关联 ug_video_info
    ug_video_info_id: int = 0
    video_name: str = ""         # ug_video_info.name
    video_type: int = 0          # ug_video_info.type  (1=电影, 2=电视剧)
    video_season: int = 0
    video_ctime: int = 0
    video_utime: int = 0
    video_collection_id: str = ""  # ug_video_info.collection_id（检测合集增删）
    fav_count: int = 0          # 收藏数（检测收藏增删）
    max_mtime: int = 0          # 五张表的最新时间戳（用于缓存决策）
    content_hash: str = ""      # 9 个用户可编辑字段的哈希（检测 u время 不变时的内容变化）
