##  一、媒体信息核心模块

### 1. `ug_video_info` — 视频主信息表
**作用**：存储所有电影、电视剧、纪录片等视频实体的元数据（最核心的表）。

| 列名                     | 数据类型     | 可空   | 默认值                                                     |
|:-----------------------|:---------|:-----|:--------------------------------------------------------|
| ug_video_info_id       | bigint   | NO   | nextval('ug_video_info_ug_video_info_id_seq'::regclass) |
| douban_id              | bigint   | YES  | 0                                                       |
| tmdb_id                | bigint   | YES  | 0                                                       |
| use_nfo                | bigint   | NO   | 1                                                       |
| name                   | text     | NO   |                                                         |
| pinyin_first           | text     | NO   |                                                         |
| pinyin_full            | text     | NO   |                                                         |
| to9_digit              | text     | YES  |                                                         |
| release_date           | bigint   | YES  | 0                                                       |
| last_release_date      | bigint   | YES  | 0                                                       |
| score                  | numeric  | YES  | 0                                                       |
| year                   | bigint   | YES  | 0                                                       |
| season                 | bigint   | YES  | 0                                                       |
| country_list           | ARRAY    | YES  |                                                         |
| style_list             | ARRAY    | YES  |                                                         |
| grading                | integer  | YES  |                                                         |
| introduction           | text     | NO   |                                                         |
| type                   | smallint | NO   | 0                                                       |
| poster_path            | text     | YES  |                                                         |
| backdrop_path          | text     | YES  |                                                         |
| logo_path              | text     | NO   | ''::text                                                |
| tagline                | text     | NO   | ''::text                                                |
| no_lang_poster_path    | text     | NO   | ''::text                                                |
| no_lang_backdrop_path  | text     | NO   | ''::text                                                |
| language               | text     | NO   |                                                         |
| category_id            | text     | NO   |                                                         |
| old_category_id        | text     | NO   |                                                         |
| all_season_episode_num | bigint   | YES  | 0                                                       |
| media_lib_set_id       | bigint   | NO   |                                                         |
| collection_id          | text     | YES  | ''::text                                                |
| collection_time        | bigint   | YES  | 0                                                       |
| last_play_file_path    | text     | NO   |                                                         |
| ctime                  | bigint   | YES  | 0                                                       |
| utime                  | bigint   | YES  | 0                                                       |
| jp_name                | text     | NO   | ''::text                                                |
| ug_media_id            | text     | NO   | ''::text                                                |

### 2. `ug_television_episode` — 电视剧剧集表
**作用**：存储电视剧每一集的具体信息。

| 列名                       | 数据类型   | 可空   | 默认值                                                                     |
|:-------------------------|:-------|:-----|:------------------------------------------------------------------------|
| ug_television_episode_id | bigint | NO   | nextval('ug_television_episode_ug_television_episode_id_seq'::regclass) |
| category_id              | text   | NO   |                                                                         |
| old_category_id          | text   | NO   |                                                                         |
| season                   | bigint | YES  | 0                                                                       |
| episode                  | bigint | YES  | 0                                                                       |
| language                 | text   | NO   |                                                                         |
| name                     | text   | NO   |                                                                         |
| overview                 | text   | NO   |                                                                         |
| cover_path               | text   | NO   |                                                                         |
| episode_flag             | text   | NO   |                                                                         |
| ctime                    | bigint | NO   | 0                                                                       |
| utime                    | bigint | NO   | 0                                                                       |
| media_lib_set_id         | bigint | NO   |                                                                         |


### 3. `ug_collection` — 合集表
**作用**：存储电影/剧集合集（如“哈利·波特系列”）。

| 列名                  | 数据类型    | 可空   | 默认值                                                     |
|:--------------------|:--------|:-----|:--------------------------------------------------------|
| ug_collection_id    | bigint  | NO   | nextval('ug_collection_ug_collection_id_seq'::regclass) |
| name                | text    | NO   |                                                         |
| pinyin_first        | text    | NO   |                                                         |
| pinyin_full         | text    | NO   |                                                         |
| poster_path         | text    | YES  |                                                         |
| backdrop_path       | text    | YES  |                                                         |
| language            | text    | NO   |                                                         |
| introduction        | text    | YES  |                                                         |
| is_manual_create    | boolean | YES  | false                                                   |
| collection_id       | text    | YES  |                                                         |
| tmdb_id             | text    | YES  | '0'::text                                               |
| media_lib_set_id    | bigint  | YES  | 0                                                       |
| year                | bigint  | YES  |                                                         |
| score               | numeric | YES  |                                                         |
| category_id_list    | ARRAY   | YES  |                                                         |
| ctime               | bigint  | NO   |                                                         |
| utime               | bigint  | NO   |                                                         |
| src_type            | integer | YES  |                                                         |
| jp_name             | text    | NO   | ''::text                                                |
| cloud_id            | text    | NO   | ''::text                                                |
| cloud_collection_id | text    | NO   | ''::text                                                |
| sort_type           | bigint  | YES  | 0                                                       |
| order_type          | bigint  | YES  | 0                                                       |


### 4. `ug_actor` — 演员表

**作用**：存储演员/导演等人物信息。


| 列名                | 数据类型              | 可空   | 默认值                                           |
|:------------------|:------------------|:-----|:----------------------------------------------|
| ug_actor_id       | bigint            | NO   | nextval('ug_actor_ug_actor_id_seq'::regclass) |
| actor_id          | bigint            | NO   |                                               |
| actor_data_source | bigint            | NO   | 0                                             |
| actor_once_id     | text              | NO   |                                               |
| name              | character varying | NO   |                                               |
| pinyin_first      | text              | NO   |                                               |
| pinyin_full       | text              | NO   |                                               |
| introduction      | text              | YES  |                                               |
| country_id        | text              | YES  |                                               |
| alias             | text              | YES  |                                               |
| birthday          | bigint            | YES  | 0                                             |
| gender            | smallint          | YES  | 0                                             |
| language          | character varying | YES  |                                               |
| avatar_url        | text              | YES  |                                               |
| lock              | boolean           | YES  | false                                         |
| source            | bigint            | YES  | 0                                             |
| ctime             | bigint            | YES  |                                               |
| utime             | bigint            | YES  |                                               |
| ug_cloud_actor_id | text              | NO   | ''::text                                      |
| tmdb_id           | bigint            | YES  | 0                                             |
| douban_id         | bigint            | YES  | 0                                             |


### 5. `ug_video_actor_relation` — 视频与演员关联表
**作用**：建立视频和演员的多对多关系。


| 列名                         | 数据类型   | 可空   | 默认值                                                                         |
|:---------------------------|:-------|:-----|:----------------------------------------------------------------------------|
| ug_video_actor_relation_id | bigint | NO   | nextval('ug_video_actor_relation_ug_video_actor_relation_id_seq'::regclass) |
| category_id                | text   | NO   |                                                                             |
| role                       | text   | YES  |                                                                             |
| actor_once_id              | text   | NO   |                                                                             |
| season                     | bigint | YES  |                                                                             |
| actor_sequence             | bigint | YES  |                                                                             |
| ctime                      | bigint | YES  |                                                                             |
| utime                      | bigint | YES  |                                                                             |
| media_lib_set_id           | bigint | NO   |                                                                             |
| department                 | text   | YES  |                                                                             |

##  二、文件管理模块

### 6. `file_info` — 文件信息主表
**作用**：存储所有媒体文件的物理信息（路径、大小、时长等）。


| 列名                     | 数据类型              | 可空   | 默认值                                        |
|:-----------------------|:------------------|:-----|:-------------------------------------------|
| file_id                | bigint            | NO   | nextval('file_info_file_id_seq'::regclass) |
| file_name              | text              | NO   | ''::text                                   |
| file_path              | text              | NO   | ''::text                                   |
| folder_path            | text              | NO   | ''::text                                   |
| bdmv_path              | text              | NO   | ''::text                                   |
| file_size              | bigint            | NO   | 0                                          |
| duration               | bigint            | NO   | 0                                          |
| season_num             | bigint            | NO   | 0                                          |
| episode_num            | bigint            | NO   | 0                                          |
| clarity                | bigint            | NO   | 99999                                      |
| audio_quality          | bigint            | NO   | 0                                          |
| video_quality          | bigint            | NO   | 0                                          |
| category_id            | text              | NO   | ''::text                                   |
| media_lib_set_id       | bigint            | NO   | 0                                          |
| use_nfo                | bigint            | NO   | 1                                          |
| is_locked              | boolean           | NO   | false                                      |
| ctime                  | bigint            | YES  | 0                                          |
| utime                  | bigint            | YES  | 0                                          |
| skipper_params         | jsonb             | NO   | '[]'::json                                 |
| skipper_analyze_status | bigint            | NO   | 0                                          |
| pinyin_first           | text              | NO   | ''::text                                   |
| pinyin_full            | text              | NO   | ''::text                                   |
| hash_fingerprint       | character varying | NO   | ''::character varying                      |


##  三、媒体库配置模块

### 11. `media_lib_set` — 媒体库设置表
**作用**：配置每一个媒体库（如“电影库”、“电视剧库”）。

| 列名                          | 数据类型    | 可空   | 默认值                                                     |
|:----------------------------|:--------|:-----|:--------------------------------------------------------|
| media_lib_set_id            | bigint  | NO   | nextval('media_lib_set_media_lib_set_id_seq'::regclass) |
| media_name                  | text    | NO   |                                                         |
| media_lib_folder_arr        | ARRAY   | NO   |                                                         |
| metadata_scraper_struct_arr | text    | YES  |                                                         |
| pic_scraper_struct_arr      | text    | YES  |                                                         |
| read_local_info_first       | boolean | YES  |                                                         |
| nfo_info_save_to_local      | boolean | YES  |                                                         |
| auto_add_to_collection      | boolean | YES  |                                                         |
| pic_res_save_to_media_dir   | boolean | YES  |                                                         |
| tv_visible                  | boolean | YES  |                                                         |
| order_sn                    | bigint  | YES  |                                                         |
| tv_rule_id                  | bigint  | YES  |                                                         |
| language                    | text    | NO   |                                                         |
| scan_status                 | integer | YES  |                                                         |
| create_time                 | bigint  | YES  |                                                         |
| filter_size                 | bigint  | YES  |                                                         |
| filter_switch               | boolean | YES  |                                                         |
| filter_set_flag             | boolean | YES  |                                                         |


##  五、播放与互动模块

### 17. `play_history` — 播放历史表
**作用**：记录用户的播放进度和观看历史。

| 列名                | 数据类型    | 可空   | 默认值                                                   |
|:------------------|:--------|:-----|:------------------------------------------------------|
| play_history_id   | bigint  | NO   | nextval('play_history_play_history_id_seq'::regclass) |
| uid               | bigint  | NO   |                                                       |
| category_id       | text    | NO   |                                                       |
| ug_video_info_id  | bigint  | NO   | 0                                                     |
| file_id           | bigint  | NO   | 0                                                     |
| media_lib_set_id  | bigint  | YES  |                                                       |
| current_play_time | bigint  | YES  | 0                                                     |
| last_access_time  | bigint  | YES  | 0                                                     |
| progress          | numeric | YES  | 0                                                     |
| create_time       | bigint  | YES  |                                                       |
| watch_status      | bigint  | YES  | 1                                                     |
| iso_ts            | text    | YES  | ''::text                                              |
| play_folder_path  | text    | YES  | ''::text                                              |


### 18. `favorites` — 收藏表
**作用**：用户收藏的视频列表。

| 列名               | 数据类型   | 可空   | 默认值                                             |
|:-----------------|:-------|:-----|:------------------------------------------------|
| favorites_id     | bigint | NO   | nextval('favorites_favorites_id_seq'::regclass) |
| uid              | bigint | NO   | 0                                               |
| once_id          | text   | NO   | '0'::text                                       |
| favorites_type   | bigint | YES  |                                                 |
| media_lib_set_id | bigint | YES  |                                                 |
| create_time      | bigint | YES  |                                                 |

### 19. `search_history` — 搜索历史
**作用**：记录用户的搜索关键词。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `search_history_id` | bigint | 主键ID |
| `uid` | bigint | 用户ID |
| `keyword` | text | 搜索关键词 |
| `create_time` | bigint | 搜索时间 |

---


##  八、统计与辅助模块

### 29. `stats_event` — 统计事件

**作用**：记录用户行为事件（用于数据分析）。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | bigint | 主键ID |
| `unique_id` | text | 唯一标识（可能为设备ID） |
| `event_type` | text | 事件类型（播放/暂停/搜索等） |
| `duration` | bigint | 事件持续时间 |
| `area` / `sub_area` | text | 区域/子区域（如“首页-推荐”） |

---