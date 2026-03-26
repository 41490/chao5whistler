use std::path::PathBuf;

use anyhow::Result;

use crate::archive;
use crate::audio;
use crate::av;
use crate::cli::{
    BuildStreamBridgeArgs, CheckConfigArgs, CliCommand, PrepareDayPackArgs, PrintDefaultConfigArgs,
    RenderAudioSampleArgs, RenderAvSampleArgs, RenderVideoSampleArgs, ReplayDryRunArgs,
    RunStreamBridgeArgs, SampleAudioArgs, SampleReplayArgs, SampleVideoArgs, SeedFixtureRawArgs,
    ValidateDayPackArgs,
};
use crate::config::{self, OutputFormat};
use crate::replay;
use crate::stage7;
use crate::video;

pub fn run<I>(args: I) -> Result<()>
where
    I: IntoIterator,
    I::Item: Into<String>,
{
    match crate::cli::parse(args)? {
        CliCommand::Help => {
            println!("{}", crate::cli::help_text());
        }
        CliCommand::CheckConfig(args) => run_check_config(args)?,
        CliCommand::PrintDefaultConfig(args) => run_print_default_config(args)?,
        CliCommand::SeedFixtureRaw(args) => run_seed_fixture_raw(args)?,
        CliCommand::PrepareDayPack(args) => run_prepare_day_pack(args)?,
        CliCommand::ValidateDayPack(args) => run_validate_day_pack(args)?,
        CliCommand::SampleReplay(args) => run_sample_replay(args)?,
        CliCommand::ReplayDryRun(args) => run_replay_dry_run(args)?,
        CliCommand::SampleAudio(args) => run_sample_audio(args)?,
        CliCommand::RenderAudioSample(args) => run_render_audio_sample(args)?,
        CliCommand::SampleVideo(args) => run_sample_video(args)?,
        CliCommand::RenderVideoSample(args) => run_render_video_sample(args)?,
        CliCommand::RenderAvSample(args) => run_render_av_sample(args)?,
        CliCommand::BuildStreamBridge(args) => run_build_stream_bridge(args)?,
        CliCommand::RunStreamBridge(args) => run_stream_bridge(args)?,
    }

    Ok(())
}

fn run_check_config(args: CheckConfigArgs) -> Result<()> {
    let config_path = args.config_path.unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, args.local_override_path.as_deref())?;

    println!("songh stage1 config validation passed");
    println!("main config: {}", config_path.display());
    match loaded.report.local_override_path {
        Some(path) => println!("local override: {}", path.display()),
        None => println!("local override: <none>"),
    }
    println!(
        "env override: SONGH_RTMP_URL {}",
        if loaded.report.env_rtmp_override_applied {
            "applied"
        } else {
            "not-set"
        }
    );
    println!("effective mode: {}", loaded.config.runtime.mode.as_str());
    println!(
        "effective archive selector: {}",
        loaded.config.archive.selector.as_str()
    );
    println!(
        "effective outputs: rtmp={} local_record={}",
        loaded.config.outputs.enable_rtmp, loaded.config.outputs.enable_local_record
    );

    if loaded.report.warnings.is_empty() {
        println!("warnings: 0");
    } else {
        println!("warnings: {}", loaded.report.warnings.len());
        for warning in &loaded.report.warnings {
            println!("- {warning}");
        }
    }

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&loaded.config)?);
    }

    Ok(())
}

fn run_print_default_config(args: PrintDefaultConfigArgs) -> Result<()> {
    match args.format {
        OutputFormat::Json => {
            println!(
                "{}",
                serde_json::to_string_pretty(&config::schema::Config::default())?
            );
        }
        OutputFormat::Toml => {
            println!("{}", config::render_default_toml()?);
        }
    }

    Ok(())
}

fn run_seed_fixture_raw(args: SeedFixtureRawArgs) -> Result<()> {
    let report = archive::seed_fixture_raw(&args.archive_root, &args.day, args.force)?;
    println!("songh stage2 fixture raw seed passed");
    println!("archive root: {}", args.archive_root.display());
    println!("source day: {}", args.day);
    println!("raw files written: {}", report.raw_file_count);
    println!("raw events written: {}", report.raw_event_count);
    Ok(())
}

fn run_prepare_day_pack(args: PrepareDayPackArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = archive::prepare_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        args.force,
        args.skip_download,
    )?;

    println!("songh stage2 day-pack prepare passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.archive_root.display());
    println!("source day: {}", report.source_day);
    println!("raw events: {}", report.raw_event_count);
    println!("normalized events: {}", report.normalized_event_count);
    println!(
        "dropped secondary events: {}",
        report.dropped_secondary_event_count
    );
    println!("manifest: {}", report.manifest_path.display());
    Ok(())
}

fn run_validate_day_pack(args: ValidateDayPackArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report =
        archive::validate_day_pack(&loaded.config, &args.day, args.archive_root.as_deref())?;

    println!("songh stage2 day-pack validation passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.archive_root.display());
    println!("source day: {}", report.source_day);
    println!("raw files: {}", report.raw_file_count);
    println!("normalized files: {}", report.normalized_file_count);
    println!("normalized events: {}", report.normalized_event_count);
    println!("minute index hours: {}", report.minute_index_hours);
    println!("manifest checksum coverage: ok");
    Ok(())
}

fn run_sample_replay(args: SampleReplayArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = replay::sample_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        args.start_second,
        args.duration_secs,
    )?;

    println!("songh stage3 replay sample passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.archive_root.display());
    println!("source day: {}", report.source_day);
    println!("start second: {}", report.start_second);
    println!("duration secs: {}", report.duration_secs);
    println!("source events: {}", report.source_event_count);
    println!("emitted events: {}", report.emitted_event_count);
    println!("deduped events: {}", report.deduped_event_count);
    println!("overflow events: {}", report.overflow_event_count);
    println!(
        "seconds with source/emission: {}/{}",
        report.seconds_with_source_events, report.seconds_with_emission
    );
    println!("config fingerprint: {}", report.config_fingerprint);

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_replay_dry_run(args: ReplayDryRunArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = replay::dry_run_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        args.start_second,
        args.duration_secs,
    )?;

    println!("songh stage3 replay dry-run passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.archive_root.display());
    println!("source day: {}", report.source_day);
    println!("start second: {}", report.start_second);
    println!("duration secs: {}", report.duration_secs);
    println!("ticks emitted: {}", report.ticks.len());

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_sample_video(args: SampleVideoArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = video::sample_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        args.start_second,
        args.duration_secs,
        args.motion_mode_override,
        args.angle_deg_override,
    )?;

    println!("songh stage4 video sample passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.archive_root.display());
    println!("source day: {}", report.source_day);
    println!("start second: {}", report.start_second);
    println!("duration secs: {}", report.duration_secs);
    println!("motion mode: {}", report.motion_mode);
    println!("emitted sprites: {}", report.emitted_sprite_count);
    println!("frames emitted: {}", report.frames.len());

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_sample_audio(args: SampleAudioArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = audio::sample_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        args.start_second,
        args.duration_secs,
    )?;

    println!("songh stage5 audio sample passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.archive_root.display());
    println!("source day: {}", report.source_day);
    println!("start second: {}", report.start_second);
    println!("duration secs: {}", report.duration_secs);
    println!("sample rate: {}", report.sample_rate);
    println!("channels: {}", report.channels);
    println!("emitted cues: {}", report.emitted_cue_count);
    println!("rendered frames: {}", report.total_frames);

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_render_audio_sample(args: RenderAudioSampleArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = audio::render_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        &args.output_dir,
        args.start_second,
        args.duration_secs,
    )?;

    println!("songh stage5 audio render passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.frame_plan.archive_root.display());
    println!("source day: {}", report.frame_plan.source_day);
    println!("output dir: {}", report.output_dir.display());
    println!("audio-plan: {}", report.audio_plan_path.display());
    println!("wav: {}", report.wav_path.display());
    println!("rendered frames: {}", report.rendered_frame_count);
    println!("rendered cues: {}", report.rendered_cue_count);
    match &report.background {
        Some(background) => {
            println!("background wav: {}", background.source_wav_path.display());
            println!(
                "background source: {} Hz, {} ch, {} frames",
                background.source_sample_rate,
                background.source_channels,
                background.source_frame_count
            );
            println!(
                "background mix: gain_db={:.2} loop={}",
                background.gain_db, background.loop_enabled
            );
        }
        None => println!("background wav: <disabled>"),
    }
    println!("peak amplitude: {:.4}", report.peak_amplitude);
    println!("wav sha256: {}", report.wav_sha256);

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_render_video_sample(args: RenderVideoSampleArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = video::render_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        &args.output_dir,
        args.start_second,
        args.duration_secs,
        args.motion_mode_override,
        args.angle_deg_override,
    )?;

    println!("songh stage4 video render passed");
    println!("main config: {}", config_path.display());
    println!("archive root: {}", report.frame_plan.archive_root.display());
    println!("source day: {}", report.frame_plan.source_day);
    println!("output dir: {}", report.output_dir.display());
    println!("frame-plan: {}", report.frame_plan_path.display());
    println!("frames dir: {}", report.frames_dir.display());
    println!("motion mode: {}", report.frame_plan.motion_mode);
    println!("rendered frames: {}", report.rendered_frame_count);
    println!(
        "rendered sprites: {}",
        report.frame_plan.emitted_sprite_count
    );
    match &report.first_active_frame_golden {
        Some(golden) => {
            println!("first active frame: {}", golden.frame_index);
            println!("first active rgba sha256: {}", golden.rgba_sha256);
        }
        None => {
            println!("first active frame: <none>");
        }
    }
    match &report.peak_density_frame_golden {
        Some(golden) => {
            println!("peak density frame: {}", golden.frame_index);
            println!("peak density rgba sha256: {}", golden.rgba_sha256);
        }
        None => {
            println!("peak density frame: <none>");
        }
    }

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_render_av_sample(args: RenderAvSampleArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = av::render_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        &args.output_dir,
        args.start_second,
        args.duration_secs,
        args.motion_mode_override,
        args.angle_deg_override,
    )?;

    println!("songh stage6 av render passed");
    println!("main config: {}", config_path.display());
    println!(
        "archive root: {}",
        report.video.frame_plan.archive_root.display()
    );
    println!("source day: {}", report.video.frame_plan.source_day);
    println!("output dir: {}", report.output_dir.display());
    println!("video dir: {}", report.video_output_dir.display());
    println!("audio dir: {}", report.audio_output_dir.display());
    println!("preview mp4: {}", report.preview_mp4_path.display());
    println!(
        "expected fps/frame_count: {}/{}",
        report.expected_fps, report.expected_frame_count
    );
    println!(
        "expected duration secs: {:.4}",
        report.expected_duration_seconds
    );
    println!(
        "encode: vcodec={} preset={} audio={}kbps",
        report.video_codec, report.video_preset, report.audio_bitrate_kbps
    );
    match &report.ffprobe_path {
        Some(path) => println!("ffprobe: {}", path.display()),
        None => println!("ffprobe: <skipped>"),
    }

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_build_stream_bridge(args: BuildStreamBridgeArgs) -> Result<()> {
    let config_path = args
        .config_path
        .clone()
        .unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, None)?;
    let report = stage7::build_day_pack(
        &loaded.config,
        &args.day,
        args.archive_root.as_deref(),
        &args.output_dir,
        args.start_second,
        args.duration_secs,
        args.motion_mode_override,
        args.angle_deg_override,
    )?;

    println!("songh stage7 stream bridge build passed");
    println!("main config: {}", config_path.display());
    println!("source day: {}", args.day);
    println!("output dir: {}", report.output_dir.display());
    println!("preview mp4: {}", report.source_preview_mp4_path.display());
    println!("smoke flv: {}", report.smoke_flv_path.display());
    println!("manifest: {}", report.manifest_path.display());
    println!("ffmpeg args: {}", report.ffmpeg_args_path.display());
    println!(
        "failure taxonomy: {}",
        report.failure_taxonomy_path.display()
    );
    println!(
        "validation report: {}",
        report.validation_report_path.display()
    );
    println!("run wrapper: {}", report.wrapper_script_path.display());

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }

    Ok(())
}

fn run_stream_bridge(args: RunStreamBridgeArgs) -> Result<()> {
    let report = stage7::run_runtime(
        &args.artifact_dir,
        &args.loop_mode,
        if args.max_runtime_secs > 0 {
            Some(args.max_runtime_secs)
        } else {
            None
        },
    )?;

    println!("songh stage7 stream bridge runtime passed");
    println!("artifact dir: {}", report.artifact_dir.display());
    println!("status: {}", report.status);
    println!(
        "preflight report: {}",
        report.preflight_report_path.display()
    );
    println!("runtime report: {}", report.runtime_report_path.display());
    println!(
        "latest exit report: {}",
        report.latest_exit_report_path.display()
    );
    println!("latest stderr log: {}", report.latest_log_path.display());
    println!(
        "attempts/final exit: {}/{}:{}",
        report.attempts_total, report.final_exit_class_id, report.final_exit_code
    );
    Ok(())
}

fn default_runtime_config_path() -> PathBuf {
    std::env::current_dir()
        .map(|cwd| cwd.join("songh.toml"))
        .unwrap_or_else(|_| PathBuf::from("songh.toml"))
}
