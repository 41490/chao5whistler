use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub meta: MetaConfig,
    pub runtime: RuntimeConfig,
    pub archive: ArchiveConfig,
    pub replay: ReplayConfig,
    pub fallback: FallbackConfig,
    pub events: EventsConfig,
    pub text: TextConfig,
    pub audio: AudioConfig,
    pub video: VideoConfig,
    pub outputs: OutputsConfig,
    pub observe: ObserveConfig,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            meta: MetaConfig::default(),
            runtime: RuntimeConfig::default(),
            archive: ArchiveConfig::default(),
            replay: ReplayConfig::default(),
            fallback: FallbackConfig::default(),
            events: EventsConfig::default(),
            text: TextConfig::default(),
            audio: AudioConfig::default(),
            video: VideoConfig::default(),
            outputs: OutputsConfig::default(),
            observe: ObserveConfig::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct MetaConfig {
    pub profile: String,
    pub label: String,
}

impl Default for MetaConfig {
    fn default() -> Self {
        Self {
            profile: "default".to_string(),
            label: "songh".to_string(),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeMode {
    ArchiveReplay,
    RandomFallback,
    DryRun,
}

impl RuntimeMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ArchiveReplay => "archive_replay",
            Self::RandomFallback => "random_fallback",
            Self::DryRun => "dry_run",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeClock {
    RealtimeDay,
    Fast,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum StartPolicy {
    Immediate,
    AlignToNextSecond,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct RuntimeConfig {
    pub mode: RuntimeMode,
    pub clock: RuntimeClock,
    pub start_policy: StartPolicy,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            mode: RuntimeMode::ArchiveReplay,
            clock: RuntimeClock::RealtimeDay,
            start_policy: StartPolicy::AlignToNextSecond,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ArchiveSelector {
    LatestCompleteDay,
    FixedDay,
}

impl ArchiveSelector {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::LatestCompleteDay => "latest_complete_day",
            Self::FixedDay => "fixed_day",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum NormalizeCodec {
    #[serde(rename = "jsonl.zst")]
    JsonlZst,
    #[serde(rename = "jsonl.gz")]
    JsonlGz,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct ArchiveConfig {
    pub root_dir: String,
    pub selector: ArchiveSelector,
    pub preferred_offset_days: u32,
    pub fixed_day: String,
    pub download: ArchiveDownloadConfig,
    pub normalize: ArchiveNormalizeConfig,
}

impl Default for ArchiveConfig {
    fn default() -> Self {
        Self {
            root_dir: "var/songh/archive".to_string(),
            selector: ArchiveSelector::LatestCompleteDay,
            preferred_offset_days: 2,
            fixed_day: String::new(),
            download: ArchiveDownloadConfig::default(),
            normalize: ArchiveNormalizeConfig::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct ArchiveDownloadConfig {
    pub enabled: bool,
    pub base_url: String,
    pub timeout_secs: u32,
    pub max_parallel: u32,
    pub user_agent: String,
}

impl Default for ArchiveDownloadConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            base_url: "https://data.gharchive.org".to_string(),
            timeout_secs: 60,
            max_parallel: 4,
            user_agent: "songh/0.1".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct ArchiveNormalizeConfig {
    pub codec: NormalizeCodec,
    pub write_minute_index: bool,
    pub write_stats: bool,
    pub drop_secondary_events: bool,
}

impl Default for ArchiveNormalizeConfig {
    fn default() -> Self {
        Self {
            codec: NormalizeCodec::JsonlZst,
            write_minute_index: true,
            write_stats: true,
            drop_secondary_events: true,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ReplaySelectionKey {
    WeightDesc,
    CreatedAtAsc,
    EventIdAsc,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OverflowPolicy {
    DropAndCount,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct ReplayConfig {
    pub max_events_per_second: u32,
    pub dedupe_window_secs: u32,
    pub selection_order: Vec<ReplaySelectionKey>,
    pub overflow_policy: OverflowPolicy,
}

impl Default for ReplayConfig {
    fn default() -> Self {
        Self {
            max_events_per_second: 4,
            dedupe_window_secs: 600,
            selection_order: vec![
                ReplaySelectionKey::WeightDesc,
                ReplaySelectionKey::EventIdAsc,
            ],
            overflow_policy: OverflowPolicy::DropAndCount,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DensitySource {
    HistoryIfAvailable,
    BuiltinOnly,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct FallbackConfig {
    pub enabled: bool,
    pub density_scale: f64,
    pub seed: u64,
    pub density_source: DensitySource,
    pub synthetic_repo_prefix: String,
    pub synthetic_actor_prefix: String,
}

impl Default for FallbackConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            density_scale: 0.5,
            seed: 0,
            density_source: DensitySource::HistoryIfAvailable,
            synthetic_repo_prefix: "synthetic/repo".to_string(),
            synthetic_actor_prefix: "synthetic_actor".to_string(),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EventType {
    CreateEvent,
    DeleteEvent,
    PushEvent,
    IssuesEvent,
    IssueCommentEvent,
    CommitCommentEvent,
    PullRequestEvent,
    PublicEvent,
    ForkEvent,
    ReleaseEvent,
}

impl EventType {
    pub const ALL: [EventType; 10] = [
        EventType::CreateEvent,
        EventType::DeleteEvent,
        EventType::PushEvent,
        EventType::IssuesEvent,
        EventType::IssueCommentEvent,
        EventType::CommitCommentEvent,
        EventType::PullRequestEvent,
        EventType::PublicEvent,
        EventType::ForkEvent,
        EventType::ReleaseEvent,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::CreateEvent => "CreateEvent",
            Self::DeleteEvent => "DeleteEvent",
            Self::PushEvent => "PushEvent",
            Self::IssuesEvent => "IssuesEvent",
            Self::IssueCommentEvent => "IssueCommentEvent",
            Self::CommitCommentEvent => "CommitCommentEvent",
            Self::PullRequestEvent => "PullRequestEvent",
            Self::PublicEvent => "PublicEvent",
            Self::ForkEvent => "ForkEvent",
            Self::ReleaseEvent => "ReleaseEvent",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct EventsConfig {
    pub primary_types: Vec<EventType>,
    pub hash_len_default: u32,
    pub weights: BTreeMap<EventType, u8>,
}

impl Default for EventsConfig {
    fn default() -> Self {
        Self {
            primary_types: EventType::ALL.to_vec(),
            hash_len_default: 8,
            weights: default_event_weights(),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum UnknownFieldPolicy {
    Error,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EmptyFieldPolicy {
    RenderEmpty,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct TextConfig {
    pub template: String,
    pub unknown_field_policy: UnknownFieldPolicy,
    pub empty_field_policy: EmptyFieldPolicy,
    pub max_rendered_chars: u32,
    pub allow_multiline: bool,
}

impl Default for TextConfig {
    fn default() -> Self {
        Self {
            template: "{repo}/{hash:8}".to_string(),
            unknown_field_policy: UnknownFieldPolicy::Error,
            empty_field_policy: EmptyFieldPolicy::RenderEmpty,
            max_rendered_chars: 64,
            allow_multiline: false,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum VoiceMode {
    Synth,
    WavSample,
    Hybrid,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct AudioConfig {
    pub sample_rate: u32,
    pub channels: u32,
    pub master_gain_db: f64,
    pub voice_mode_default: VoiceMode,
    pub background: AudioBackgroundConfig,
    pub mix: AudioMixConfig,
    pub voices: BTreeMap<EventType, VoiceConfig>,
}

impl Default for AudioConfig {
    fn default() -> Self {
        Self {
            sample_rate: 48_000,
            channels: 2,
            master_gain_db: 0.0,
            voice_mode_default: VoiceMode::Hybrid,
            background: AudioBackgroundConfig::default(),
            mix: AudioMixConfig::default(),
            voices: default_voice_configs(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct AudioBackgroundConfig {
    pub enabled: bool,
    pub wav_path: String,
    pub gain_db: f64,
    pub r#loop: bool,
}

impl Default for AudioBackgroundConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            wav_path: String::new(),
            gain_db: -9.0,
            r#loop: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct AudioMixConfig {
    pub crossfade_ms: u32,
    pub limiter_enabled: bool,
    pub limiter_ceiling_dbfs: f64,
}

impl Default for AudioMixConfig {
    fn default() -> Self {
        Self {
            crossfade_ms: 80,
            limiter_enabled: true,
            limiter_ceiling_dbfs: -1.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct VoiceConfig {
    pub enabled: bool,
    pub mode: VoiceMode,
    pub preset: String,
    pub sample_path: String,
    pub gain_db: f64,
    pub duration_ms: u32,
    pub pan: f64,
}

impl Default for VoiceConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            mode: VoiceMode::Hybrid,
            preset: "voice".to_string(),
            sample_path: String::new(),
            gain_db: 0.0,
            duration_ms: 900,
            pan: 0.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct VideoConfig {
    pub canvas: VideoCanvasConfig,
    pub palette: VideoPaletteConfig,
    pub text: VideoTextConfig,
    pub motion: VideoMotionConfig,
}

impl Default for VideoConfig {
    fn default() -> Self {
        Self {
            canvas: VideoCanvasConfig::default(),
            palette: VideoPaletteConfig::default(),
            text: VideoTextConfig::default(),
            motion: VideoMotionConfig::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct VideoCanvasConfig {
    pub width: u32,
    pub height: u32,
    pub fps: u32,
}

impl Default for VideoCanvasConfig {
    fn default() -> Self {
        Self {
            width: 1280,
            height: 720,
            fps: 30,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PaletteTheme {
    SolarizedDark,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct VideoPaletteConfig {
    pub theme: PaletteTheme,
    pub background_hex: String,
    pub text_hex: String,
    pub accent_hex: String,
}

impl Default for VideoPaletteConfig {
    fn default() -> Self {
        Self {
            theme: PaletteTheme::SolarizedDark,
            background_hex: "#002b36".to_string(),
            text_hex: "#fdf6e3".to_string(),
            accent_hex: "#b58900".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct VideoTextConfig {
    pub font_path: String,
    pub font_size_min: u32,
    pub font_size_max: u32,
    pub stroke_width: u32,
    pub initial_alpha: u32,
    pub bottom_spawn_min_ratio: f64,
    pub bottom_spawn_max_ratio: f64,
}

impl Default for VideoTextConfig {
    fn default() -> Self {
        Self {
            font_path: "ops/assets/3270NerdFontMono-Condensed.ttf".to_string(),
            font_size_min: 14,
            font_size_max: 42,
            stroke_width: 2,
            initial_alpha: 220,
            bottom_spawn_min_ratio: 0.50,
            bottom_spawn_max_ratio: 0.95,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MotionMode {
    Vertical,
    FixedAngle,
    RandomAngle,
}

impl MotionMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Vertical => "vertical",
            Self::FixedAngle => "fixed_angle",
            Self::RandomAngle => "random_angle",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct VideoMotionConfig {
    pub mode: MotionMode,
    pub angle_deg: f64,
    pub random_min_deg: f64,
    pub random_max_deg: f64,
    pub speed_px_per_sec: f64,
}

impl Default for VideoMotionConfig {
    fn default() -> Self {
        Self {
            mode: MotionMode::Vertical,
            angle_deg: 0.0,
            random_min_deg: -25.0,
            random_max_deg: 25.0,
            speed_px_per_sec: 180.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct OutputsConfig {
    pub enable_rtmp: bool,
    pub enable_local_record: bool,
    pub tee_muxer: bool,
    pub encode: OutputEncodeConfig,
    pub rtmp: RtmpOutputConfig,
    pub record: RecordOutputConfig,
}

impl Default for OutputsConfig {
    fn default() -> Self {
        Self {
            enable_rtmp: false,
            enable_local_record: true,
            tee_muxer: true,
            encode: OutputEncodeConfig::default(),
            rtmp: RtmpOutputConfig::default(),
            record: RecordOutputConfig::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct OutputEncodeConfig {
    pub video_codec: String,
    pub video_preset: String,
    pub audio_bitrate_kbps: u32,
}

impl Default for OutputEncodeConfig {
    fn default() -> Self {
        Self {
            video_codec: "h264".to_string(),
            video_preset: "ultrafast".to_string(),
            audio_bitrate_kbps: 128,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OutputContainer {
    Flv,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct RtmpOutputConfig {
    pub url: String,
    pub container: OutputContainer,
}

impl Default for RtmpOutputConfig {
    fn default() -> Self {
        Self {
            url: String::new(),
            container: OutputContainer::Flv,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct RecordOutputConfig {
    pub enabled: bool,
    pub path: String,
    pub container: OutputContainer,
}

impl Default for RecordOutputConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            path: "var/songh/records/{date}/{label}.flv".to_string(),
            container: OutputContainer::Flv,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct ObserveConfig {
    pub log_level: LogLevel,
    pub emit_stats_every_secs: u32,
    pub write_runtime_report: bool,
}

impl Default for ObserveConfig {
    fn default() -> Self {
        Self {
            log_level: LogLevel::Info,
            emit_stats_every_secs: 30,
            write_runtime_report: true,
        }
    }
}

fn default_event_weights() -> BTreeMap<EventType, u8> {
    BTreeMap::from([
        (EventType::CreateEvent, 10),
        (EventType::DeleteEvent, 20),
        (EventType::PushEvent, 30),
        (EventType::IssuesEvent, 40),
        (EventType::IssueCommentEvent, 50),
        (EventType::CommitCommentEvent, 60),
        (EventType::PullRequestEvent, 70),
        (EventType::PublicEvent, 80),
        (EventType::ForkEvent, 90),
        (EventType::ReleaseEvent, 100),
    ])
}

fn default_voice_configs() -> BTreeMap<EventType, VoiceConfig> {
    BTreeMap::from([
        (
            EventType::CreateEvent,
            VoiceConfig {
                preset: "seal_bark".to_string(),
                gain_db: -2.0,
                duration_ms: 700,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::DeleteEvent,
            VoiceConfig {
                preset: "urchin_snap".to_string(),
                gain_db: -1.0,
                duration_ms: 650,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::PushEvent,
            VoiceConfig {
                preset: "dolphin_click".to_string(),
                duration_ms: 900,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::IssuesEvent,
            VoiceConfig {
                preset: "humpback_moan".to_string(),
                gain_db: 1.0,
                duration_ms: 1100,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::IssueCommentEvent,
            VoiceConfig {
                preset: "beluga_chirp".to_string(),
                gain_db: 2.0,
                duration_ms: 900,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::CommitCommentEvent,
            VoiceConfig {
                preset: "seahorse_click".to_string(),
                gain_db: 2.5,
                duration_ms: 750,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::PullRequestEvent,
            VoiceConfig {
                preset: "orca_call".to_string(),
                gain_db: 3.0,
                duration_ms: 1200,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::PublicEvent,
            VoiceConfig {
                preset: "blue_whale_boom".to_string(),
                gain_db: 4.0,
                duration_ms: 1400,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::ForkEvent,
            VoiceConfig {
                preset: "clownfish_pop".to_string(),
                gain_db: 5.0,
                duration_ms: 1300,
                ..VoiceConfig::default()
            },
        ),
        (
            EventType::ReleaseEvent,
            VoiceConfig {
                preset: "pod_chorus".to_string(),
                gain_db: 6.0,
                duration_ms: 1600,
                ..VoiceConfig::default()
            },
        ),
    ])
}
