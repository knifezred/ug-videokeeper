"""数据模型 — 对应数据库表与 NFO 结构"""
from dataclasses import dataclass, field
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
class UgreenMeta:
    """绿联扩展字段 — 对应 <ugreen> 节点，用于同步决策"""
    ug_video_info_id: int = 0
    category_id: str = ""
    use_nfo: int = 1
    media_lib_set_id: int = 0
    collection: Optional[Collection] = None
    play_history: list[PlayHistory] = field(default_factory=list)
    favorites: list[Favorite] = field(default_factory=list)
    genre: list[str] = field(default_factory=list)
    fileinfo: Optional[FileInfo] = None
    ctime: int = 0
    utime: int = 0


@dataclass
class TvEpisodeRecord:
    """ugreen_tv.nfo 中的单集数据（对应 ug_television_episode 表）"""
    ug_television_episode_id: int = 0
    season: int = 0
    episode: int = 0
    name: str = ""
    overview: str = ""
    cover_path: str = ""
    language: str = ""
    episode_flag: str = ""
    ctime: int = 0
    utime: int = 0
    media_lib_set_id: int = 0


@dataclass
class TvSeasonRecord:
    """ugreen_tv.nfo 中的季数据（ug_video_info + 单集列表 + 关联数据）"""
    category_id: str = ""
    ug_video_info_id: int = 0
    name: str = ""
    year: int = 0
    season: int = 0
    introduction: str = ""
    score: float = 0.0
    douban_id: int = 0
    tmdb_id: int = 0
    release_date: int = 0
    use_nfo: int = 1
    grading: int = 0
    country_list: list = field(default_factory=list)
    style_list: list = field(default_factory=list)
    all_season_episode_num: int = 0
    media_lib_set_id: int = 0
    ctime: int = 0
    utime: int = 0
    episodes: list[TvEpisodeRecord] = field(default_factory=list)
    play_history: list[PlayHistory] = field(default_factory=list)
    favorites: list[Favorite] = field(default_factory=list)
    collection: Optional[Collection] = None
    genre: list[str] = field(default_factory=list)


@dataclass
class NfoRecord:
    """一个完整的 NFO 文件解析结果"""
    nfo_type: str = ""           # "movie" | "tvshow" | "season" | "episode"
    nfo_path: str = ""
    video_dir: str = ""
    official: VideoMeta = field(default_factory=VideoMeta)
    ugreen: UgreenMeta = field(default_factory=UgreenMeta)
    has_ugreen: bool = False     # NFO 文件中是否存在 <ugreen> 节点
    # 记录 NFO 中实际出现了哪些官方字段（用于精确覆写）
    official_fields_present: set[str] = field(default_factory=set)


@dataclass
class DbRecord:
    """数据库查询结果 — ug_video_info 行"""
    ug_video_info_id: int = 0
    category_id: str = ""
    name: str = ""
    douban_id: int = 0
    tmdb_id: int = 0
    use_nfo: int = 1
    score: float = 0.0
    year: int = 0
    season: int = 0
    introduction: str = ""
    country_list: list[str] = field(default_factory=list)
    style_list: list[str] = field(default_factory=list)
    grading: int = 0
    release_date: int = 0
    poster_path: str = ""
    backdrop_path: str = ""
    logo_path: str = ""
    tagline: str = ""
    language: str = ""
    collection_id: str = ""
    collection_time: int = 0
    media_lib_set_id: int = 0
    all_season_episode_num: int = 0
    ctime: int = 0
    utime: int = 0


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
