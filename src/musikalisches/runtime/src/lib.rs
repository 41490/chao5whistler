use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::f64::consts::PI;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use hound::{SampleFormat, WavSpec, WavWriter};
use serde::{Deserialize, Serialize};

pub const CANONICAL_WORK_ID: &str = "mozart_dicegame_print_1790s";
pub const POSITION_COUNT: usize = 16;
pub const DEFAULT_TEMPO_BPM: f64 = 120.0;
pub const DEFAULT_SAMPLE_RATE: u32 = 44_100;
pub const DEMO_ROLLS: [u8; POSITION_COUNT] = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 7, 6, 5, 4, 3];

const FRAGMENTS_PATH: &str =
    "docs/study/music_dice_games_package/mozart_dicegame_print_1790s/ingest/fragments.json";
const RULES_PATH: &str =
    "docs/study/music_dice_games_package/mozart_dicegame_print_1790s/rules.json";
const REALIZED_FRAGMENT_SEQUENCE_FILE: &str = "realized_fragment_sequence.json";
const NOTE_EVENT_SEQUENCE_FILE: &str = "note_event_sequence.json";
const RENDER_REQUEST_FILE: &str = "render_request.json";
const M1_VALIDATION_REPORT_FILE: &str = "m1_validation_report.json";
const OFFLINE_AUDIO_FILE: &str = "offline_audio.wav";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CommandKind {
    Realize,
    RenderAudio,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CliConfig {
    pub command: CommandKind,
    pub work_id: String,
    pub output_dir: PathBuf,
    pub rolls: Vec<u8>,
    pub tempo_bpm: f64,
    pub sample_rate: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactPaths {
    pub output_dir: PathBuf,
    pub realized_fragment_sequence: PathBuf,
    pub note_event_sequence: PathBuf,
    pub render_request: PathBuf,
    pub validation_report: PathBuf,
    pub offline_audio: Option<PathBuf>,
}

#[derive(Debug, Clone)]
pub struct LoadedContracts {
    pub rules: RulesPayload,
    pub ingest: FragmentsPayload,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RulesPayload {
    pub work_id: String,
    pub position_labels: Vec<String>,
    pub selector: SelectorSpec,
    pub columns: BTreeMap<String, RuleColumn>,
    pub status: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SelectorSpec {
    #[serde(rename = "type")]
    pub selector_type: String,
    pub allowed_values: Vec<u8>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RuleColumn {
    pub position_index: u8,
    pub fragment_ids_by_roll: BTreeMap<String, u16>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FragmentsPayload {
    pub work_id: String,
    pub status: String,
    pub fragments: Vec<Fragment>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Fragment {
    pub fragment_id: u16,
    pub measure_number: u16,
    pub source_measure_sequence_index: u16,
    pub position_label: String,
    pub position_index: u8,
    pub selector_binding: FragmentSelectorBinding,
    pub source_location: FragmentSourceLocation,
    pub duration_quarter_length: f64,
    pub time_signature: String,
    pub parts: Vec<FragmentPart>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FragmentSelectorBinding {
    #[serde(rename = "selector_type")]
    pub selector_type: String,
    pub selector_value: u8,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct FragmentSourceLocation {
    pub canonical_witness_id: String,
    pub publication_page: u8,
    pub row_index: u8,
    pub slot_index: u8,
    pub scan_canvas_index: u8,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FragmentPart {
    pub part_index: u8,
    pub source_part_id: String,
    pub source_part_name: String,
    pub source_part_abbreviation: String,
    pub source_event_count: u16,
    pub normalized_event_count: u16,
    pub note_event_count: u16,
    pub chord_event_count: u16,
    pub rest_event_count: u16,
    pub sounding_event_count: u16,
    pub inserted_implicit_rest_event_count: u16,
    pub source_duration_quarter_length: f64,
    pub normalized_duration_quarter_length: f64,
    pub is_empty_in_source: bool,
    pub contains_only_rests_after_normalization: bool,
    pub events: Vec<FragmentTimelineEvent>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FragmentTimelineEvent {
    pub event_index: u16,
    pub kind: String,
    pub offset_quarter_length: f64,
    pub duration_quarter_length: f64,
    pub end_offset_quarter_length: f64,
    pub is_sounding: bool,
    pub source_encoding: String,
    pub source_event_index: Option<u16>,
    pub pitches: Vec<FragmentPitch>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FragmentPitch {
    pub name_with_octave: String,
    pub midi: u8,
}

#[derive(Debug, Clone, Serialize)]
pub struct RenderRequest {
    pub work_id: String,
    pub command: String,
    pub rolls: Vec<u8>,
    pub tempo_bpm: f64,
    pub sample_rate: u32,
    pub selector_count: usize,
    pub output_dir: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct RealizedFragmentSequence {
    pub work_id: String,
    pub command: String,
    pub rolls: Vec<u8>,
    pub tempo_bpm: f64,
    pub total_duration_quarter_length: f64,
    pub total_duration_seconds: f64,
    pub fragments: Vec<RealizedFragmentStep>,
    pub summary: RealizedFragmentSummary,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct RealizedFragmentStep {
    pub step_index: usize,
    pub position_label: String,
    pub position_index: u8,
    pub selector_value: u8,
    pub fragment_id: u16,
    pub measure_number: u16,
    pub source_measure_sequence_index: u16,
    pub duration_quarter_length: f64,
    pub start_quarter_length: f64,
    pub end_quarter_length: f64,
    pub start_seconds: f64,
    pub end_seconds: f64,
    pub part_count: usize,
    pub source_location: FragmentSourceLocation,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct RealizedFragmentSummary {
    pub fragment_count: usize,
    pub unique_fragment_count: usize,
    pub total_part_count: usize,
    pub total_duration_quarter_length: f64,
    pub total_duration_seconds: f64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct NoteEventSequence {
    pub work_id: String,
    pub command: String,
    pub rolls: Vec<u8>,
    pub tempo_bpm: f64,
    pub sample_rate: u32,
    pub total_duration_quarter_length: f64,
    pub total_duration_seconds: f64,
    pub note_events: Vec<NoteEvent>,
    pub summary: NoteEventSummary,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct NoteEvent {
    pub note_event_index: usize,
    pub step_index: usize,
    pub position_label: String,
    pub selector_value: u8,
    pub fragment_id: u16,
    pub measure_number: u16,
    pub part_index: u8,
    pub source_part_id: String,
    pub source_part_name: String,
    pub source_part_abbreviation: String,
    pub source_event_index: Option<u16>,
    pub source_event_kind: String,
    pub source_encoding: String,
    pub pitch_name_with_octave: String,
    pub midi: u8,
    pub frequency_hz: f64,
    pub start_quarter_length: f64,
    pub duration_quarter_length: f64,
    pub end_quarter_length: f64,
    pub start_seconds: f64,
    pub duration_seconds: f64,
    pub end_seconds: f64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct NoteEventSummary {
    pub note_event_count: usize,
    pub fragment_count: usize,
    pub distinct_pitch_count: usize,
    pub total_duration_quarter_length: f64,
    pub total_duration_seconds: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct M1ValidationReport {
    pub work_id: String,
    pub stage: String,
    pub status: String,
    pub command: String,
    pub input_rolls: Vec<u8>,
    pub checks: Vec<ValidationCheck>,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
    pub summary: ValidationSummary,
    pub output_files: OutputFiles,
}

#[derive(Debug, Clone, Serialize)]
pub struct ValidationCheck {
    pub check_id: String,
    pub status: String,
    pub details: serde_json::Value,
}

#[derive(Debug, Clone, Serialize)]
pub struct ValidationSummary {
    pub selector_count: usize,
    pub fragment_count: usize,
    pub note_event_count: usize,
    pub total_duration_quarter_length: f64,
    pub total_duration_seconds: f64,
    pub tempo_bpm: f64,
    pub sample_rate: u32,
    pub checks_passed: usize,
    pub checks_failed: usize,
    pub audio_frames: Option<u32>,
    pub peak_amplitude: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct OutputFiles {
    pub render_request: String,
    pub realized_fragment_sequence: String,
    pub note_event_sequence: String,
    pub validation_report: String,
    pub offline_audio: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AudioRenderSummary {
    pub path: String,
    pub sample_rate: u32,
    pub channels: u16,
    pub frames: u32,
    pub duration_seconds: f64,
    pub peak_amplitude: f64,
    pub normalization_gain: f64,
}

pub fn run_cli<I>(args: I) -> Result<()>
where
    I: IntoIterator,
    I::Item: Into<String>,
{
    let args: Vec<String> = args.into_iter().map(Into::into).collect();
    if args.is_empty() || matches!(args[0].as_str(), "help" | "--help" | "-h") {
        print_usage();
        return Ok(());
    }

    let config = parse_cli(args)?;
    let artifacts = run_command(&config)?;
    print_summary(&config, &artifacts);
    Ok(())
}

fn print_usage() {
    println!(
        "musikalisches\n\
         \n\
         Commands:\n\
           realize       Resolve a deterministic 16-step fragment sequence and note events\n\
           render-audio  Resolve the sequence and render offline_audio.wav\n\
         \n\
         Common flags:\n\
           --work mozart_dicegame_print_1790s\n\
           --output-dir <dir>\n\
           --rolls 2,3,4,...,12\n\
           --demo-rolls\n\
           --tempo-bpm 120\n\
           --sample-rate 44100\n"
    );
}

pub fn parse_cli(args: Vec<String>) -> Result<CliConfig> {
    let command = match args.first().map(String::as_str) {
        Some("realize") => CommandKind::Realize,
        Some("render-audio") => CommandKind::RenderAudio,
        Some(other) => bail!("unsupported command: {other}"),
        None => bail!("missing command"),
    };

    let mut work_id = CANONICAL_WORK_ID.to_string();
    let mut output_dir = None;
    let mut rolls = None;
    let mut use_demo_rolls = false;
    let mut tempo_bpm = DEFAULT_TEMPO_BPM;
    let mut sample_rate = DEFAULT_SAMPLE_RATE;

    let mut index = 1;
    while index < args.len() {
        match args[index].as_str() {
            "--work" => {
                index += 1;
                let value = args.get(index).context("--work requires a value")?;
                work_id = value.clone();
            }
            "--output-dir" => {
                index += 1;
                let value = args.get(index).context("--output-dir requires a value")?;
                output_dir = Some(PathBuf::from(value));
            }
            "--rolls" => {
                index += 1;
                let value = args.get(index).context("--rolls requires a value")?;
                rolls = Some(parse_rolls(value)?);
            }
            "--demo-rolls" => {
                use_demo_rolls = true;
            }
            "--tempo-bpm" => {
                index += 1;
                let value = args.get(index).context("--tempo-bpm requires a value")?;
                tempo_bpm = value
                    .parse::<f64>()
                    .with_context(|| format!("invalid tempo bpm: {value}"))?;
            }
            "--sample-rate" => {
                index += 1;
                let value = args.get(index).context("--sample-rate requires a value")?;
                sample_rate = value
                    .parse::<u32>()
                    .with_context(|| format!("invalid sample rate: {value}"))?;
            }
            flag => bail!("unsupported flag: {flag}"),
        }
        index += 1;
    }

    if work_id != CANONICAL_WORK_ID {
        bail!("unsupported work id: {work_id}; only {CANONICAL_WORK_ID} is available in stage 5");
    }
    if tempo_bpm <= 0.0 {
        bail!("tempo bpm must be > 0");
    }
    if sample_rate < 8_000 {
        bail!("sample rate must be >= 8000");
    }

    if use_demo_rolls && rolls.is_some() {
        bail!("use either --rolls or --demo-rolls, not both");
    }
    let rolls = if use_demo_rolls {
        DEMO_ROLLS.to_vec()
    } else {
        rolls.context("missing --rolls or --demo-rolls")?
    };

    Ok(CliConfig {
        command,
        work_id,
        output_dir: output_dir.context("missing --output-dir")?,
        rolls,
        tempo_bpm,
        sample_rate,
    })
}

pub fn parse_rolls(value: &str) -> Result<Vec<u8>> {
    let rolls: Vec<u8> = value
        .split(',')
        .filter(|item| !item.trim().is_empty())
        .map(|item| {
            item.trim()
                .parse::<u8>()
                .with_context(|| format!("invalid selector value: {item}"))
        })
        .collect::<Result<Vec<u8>>>()?;
    if rolls.len() != POSITION_COUNT {
        bail!(
            "expected exactly {POSITION_COUNT} selector values, received {}",
            rolls.len()
        );
    }
    Ok(rolls)
}

pub fn run_command(config: &CliConfig) -> Result<ArtifactPaths> {
    let contracts = load_contracts(&config.work_id)?;
    let realization = realize_sequence(&contracts, &config.rolls, config.tempo_bpm)?;
    let note_events = build_note_event_sequence(
        &contracts,
        &realization,
        &config.rolls,
        config.tempo_bpm,
        config.sample_rate,
    )?;
    let replay = realize_sequence(&contracts, &config.rolls, config.tempo_bpm)?;
    let replay_events = build_note_event_sequence(
        &contracts,
        &replay,
        &config.rolls,
        config.tempo_bpm,
        config.sample_rate,
    )?;

    let render_request = RenderRequest {
        work_id: config.work_id.clone(),
        command: command_name(&config.command).to_string(),
        rolls: config.rolls.clone(),
        tempo_bpm: config.tempo_bpm,
        sample_rate: config.sample_rate,
        selector_count: config.rolls.len(),
        output_dir: config.output_dir.display().to_string(),
    };

    fs::create_dir_all(&config.output_dir)
        .with_context(|| format!("failed to create {}", config.output_dir.display()))?;

    let realized_path = config.output_dir.join(REALIZED_FRAGMENT_SEQUENCE_FILE);
    let note_event_path = config.output_dir.join(NOTE_EVENT_SEQUENCE_FILE);
    let request_path = config.output_dir.join(RENDER_REQUEST_FILE);
    let validation_path = config.output_dir.join(M1_VALIDATION_REPORT_FILE);

    write_json(&request_path, &render_request)?;
    write_json(&realized_path, &realization)?;
    write_json(&note_event_path, &note_events)?;

    let audio_summary = match config.command {
        CommandKind::Realize => None,
        CommandKind::RenderAudio => {
            let path = config.output_dir.join(OFFLINE_AUDIO_FILE);
            Some(render_wav(&note_events, &path, config.sample_rate)?)
        }
    };

    let report = build_validation_report(
        config,
        &contracts,
        &realization,
        &note_events,
        replay == realization,
        replay_events == note_events,
        audio_summary.as_ref(),
    );
    write_json(&validation_path, &report)?;

    Ok(ArtifactPaths {
        output_dir: config.output_dir.clone(),
        realized_fragment_sequence: realized_path,
        note_event_sequence: note_event_path,
        render_request: request_path,
        validation_report: validation_path,
        offline_audio: audio_summary.map(|summary| config.output_dir.join(summary.path)),
    })
}

pub fn load_contracts(work_id: &str) -> Result<LoadedContracts> {
    if work_id != CANONICAL_WORK_ID {
        bail!("unknown work id: {work_id}");
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let rules_path = root.join(RULES_PATH);
    let fragments_path = root.join(FRAGMENTS_PATH);

    let rules: RulesPayload = read_json(&rules_path)?;
    let ingest: FragmentsPayload = read_json(&fragments_path)?;

    if rules.work_id != CANONICAL_WORK_ID {
        bail!("rules.json work_id mismatch: {}", rules.work_id);
    }
    if rules.status != "stage3_rules_frozen" {
        bail!("rules.json must remain stage3_rules_frozen");
    }
    if rules.position_labels.len() != POSITION_COUNT {
        bail!("rules.json position label count must equal {POSITION_COUNT}");
    }
    if rules.selector.selector_type != "sum_of_two_d6" {
        bail!("rules selector type must be sum_of_two_d6");
    }

    if ingest.work_id != CANONICAL_WORK_ID {
        bail!("fragments.json work_id mismatch: {}", ingest.work_id);
    }
    if ingest.status != "stage4_ingest_frozen" {
        bail!("fragments.json must remain stage4_ingest_frozen");
    }
    if ingest.fragments.len() != 176 {
        bail!("fragments.json must contain exactly 176 fragments");
    }

    Ok(LoadedContracts { rules, ingest })
}

pub fn realize_sequence(
    contracts: &LoadedContracts,
    rolls: &[u8],
    tempo_bpm: f64,
) -> Result<RealizedFragmentSequence> {
    if rolls.len() != POSITION_COUNT {
        bail!(
            "expected exactly {POSITION_COUNT} selector values, received {}",
            rolls.len()
        );
    }

    let allowed: BTreeSet<u8> = contracts
        .rules
        .selector
        .allowed_values
        .iter()
        .copied()
        .collect();
    let fragment_index: HashMap<u16, &Fragment> = contracts
        .ingest
        .fragments
        .iter()
        .map(|fragment| (fragment.fragment_id, fragment))
        .collect();

    let seconds_per_quarter = 60.0 / tempo_bpm;
    let mut cursor_quarter = 0.0;
    let mut realized_steps = Vec::with_capacity(POSITION_COUNT);

    for (step_index, (position_label, selector_value)) in contracts
        .rules
        .position_labels
        .iter()
        .zip(rolls.iter().copied())
        .enumerate()
    {
        if !allowed.contains(&selector_value) {
            bail!(
                "selector value {selector_value} at step {} is outside the allowed domain",
                step_index + 1
            );
        }
        let column = contracts
            .rules
            .columns
            .get(position_label)
            .with_context(|| format!("missing rule column for {position_label}"))?;
        let fragment_id = column
            .fragment_ids_by_roll
            .get(&selector_value.to_string())
            .copied()
            .with_context(|| {
                format!("no fragment id bound to position {position_label} roll {selector_value}")
            })?;
        let fragment = fragment_index
            .get(&fragment_id)
            .copied()
            .with_context(|| format!("missing ingest fragment {fragment_id}"))?;

        if fragment.position_label != *position_label {
            bail!(
                "fragment {} position_label mismatch: ingest={} rules={}",
                fragment.fragment_id,
                fragment.position_label,
                position_label
            );
        }
        if fragment.position_index != column.position_index {
            bail!(
                "fragment {} position_index mismatch: ingest={} rules={}",
                fragment.fragment_id,
                fragment.position_index,
                column.position_index
            );
        }
        if fragment.selector_binding.selector_type != "sum_of_two_d6" {
            bail!("fragment {} selector_type mismatch", fragment.fragment_id);
        }
        if fragment.selector_binding.selector_value != selector_value {
            bail!(
                "fragment {} selector mismatch: ingest={} requested={}",
                fragment.fragment_id,
                fragment.selector_binding.selector_value,
                selector_value
            );
        }
        if fragment.measure_number != fragment.fragment_id {
            bail!(
                "fragment {} measure_number must equal fragment_id",
                fragment.fragment_id
            );
        }
        for part in &fragment.parts {
            if (part.normalized_duration_quarter_length - fragment.duration_quarter_length).abs()
                > 1e-9
            {
                bail!(
                    "fragment {} part {} normalized_duration_quarter_length mismatch",
                    fragment.fragment_id,
                    part.part_index
                );
            }
        }

        let start_quarter = cursor_quarter;
        let end_quarter = start_quarter + fragment.duration_quarter_length;
        realized_steps.push(RealizedFragmentStep {
            step_index: step_index + 1,
            position_label: position_label.clone(),
            position_index: column.position_index,
            selector_value,
            fragment_id,
            measure_number: fragment.measure_number,
            source_measure_sequence_index: fragment.source_measure_sequence_index,
            duration_quarter_length: fragment.duration_quarter_length,
            start_quarter_length: round6(start_quarter),
            end_quarter_length: round6(end_quarter),
            start_seconds: round6(start_quarter * seconds_per_quarter),
            end_seconds: round6(end_quarter * seconds_per_quarter),
            part_count: fragment.parts.len(),
            source_location: fragment.source_location.clone(),
        });
        cursor_quarter = end_quarter;
    }

    let unique_fragment_count = realized_steps
        .iter()
        .map(|step| step.fragment_id)
        .collect::<BTreeSet<_>>()
        .len();

    Ok(RealizedFragmentSequence {
        work_id: contracts.rules.work_id.clone(),
        command: "realize".to_string(),
        rolls: rolls.to_vec(),
        tempo_bpm,
        total_duration_quarter_length: round6(cursor_quarter),
        total_duration_seconds: round6(cursor_quarter * seconds_per_quarter),
        fragments: realized_steps,
        summary: RealizedFragmentSummary {
            fragment_count: POSITION_COUNT,
            unique_fragment_count,
            total_part_count: POSITION_COUNT * 2,
            total_duration_quarter_length: round6(cursor_quarter),
            total_duration_seconds: round6(cursor_quarter * seconds_per_quarter),
        },
    })
}

pub fn build_note_event_sequence(
    contracts: &LoadedContracts,
    realization: &RealizedFragmentSequence,
    rolls: &[u8],
    tempo_bpm: f64,
    sample_rate: u32,
) -> Result<NoteEventSequence> {
    let seconds_per_quarter = 60.0 / tempo_bpm;
    let fragment_index: HashMap<u16, &Fragment> = contracts
        .ingest
        .fragments
        .iter()
        .map(|fragment| (fragment.fragment_id, fragment))
        .collect();

    let mut note_events = Vec::new();

    for step in &realization.fragments {
        let fragment = fragment_index
            .get(&step.fragment_id)
            .copied()
            .with_context(|| {
                format!(
                    "missing fragment {} during note-event build",
                    step.fragment_id
                )
            })?;

        for part in &fragment.parts {
            let mut previous_end = 0.0;
            for event in &part.events {
                if (event.offset_quarter_length - previous_end).abs() > 1e-9 {
                    bail!(
                        "fragment {} part {} has a gap or overlap before event {}",
                        fragment.fragment_id,
                        part.part_index,
                        event.event_index
                    );
                }
                previous_end = event.end_offset_quarter_length;

                if !event.is_sounding {
                    continue;
                }
                for pitch in &event.pitches {
                    let start_quarter = step.start_quarter_length + event.offset_quarter_length;
                    let duration_quarter = event.duration_quarter_length;
                    let end_quarter = step.start_quarter_length + event.end_offset_quarter_length;
                    let start_seconds = start_quarter * seconds_per_quarter;
                    let duration_seconds = duration_quarter * seconds_per_quarter;
                    let end_seconds = end_quarter * seconds_per_quarter;

                    note_events.push(NoteEvent {
                        note_event_index: note_events.len() + 1,
                        step_index: step.step_index,
                        position_label: step.position_label.clone(),
                        selector_value: step.selector_value,
                        fragment_id: fragment.fragment_id,
                        measure_number: fragment.measure_number,
                        part_index: part.part_index,
                        source_part_id: part.source_part_id.clone(),
                        source_part_name: part.source_part_name.clone(),
                        source_part_abbreviation: part.source_part_abbreviation.clone(),
                        source_event_index: event.source_event_index,
                        source_event_kind: event.kind.clone(),
                        source_encoding: event.source_encoding.clone(),
                        pitch_name_with_octave: pitch.name_with_octave.clone(),
                        midi: pitch.midi,
                        frequency_hz: round6(midi_to_frequency(pitch.midi)),
                        start_quarter_length: round6(start_quarter),
                        duration_quarter_length: round6(duration_quarter),
                        end_quarter_length: round6(end_quarter),
                        start_seconds: round6(start_seconds),
                        duration_seconds: round6(duration_seconds),
                        end_seconds: round6(end_seconds),
                    });
                }
            }
        }
    }

    let distinct_pitch_count = note_events
        .iter()
        .map(|event| event.midi)
        .collect::<BTreeSet<_>>()
        .len();

    let note_event_count = note_events.len();

    Ok(NoteEventSequence {
        work_id: contracts.rules.work_id.clone(),
        command: "realize".to_string(),
        rolls: rolls.to_vec(),
        tempo_bpm,
        sample_rate,
        total_duration_quarter_length: realization.total_duration_quarter_length,
        total_duration_seconds: realization.total_duration_seconds,
        note_events,
        summary: NoteEventSummary {
            note_event_count,
            fragment_count: realization.fragments.len(),
            distinct_pitch_count,
            total_duration_quarter_length: realization.total_duration_quarter_length,
            total_duration_seconds: realization.total_duration_seconds,
        },
    })
}

pub fn render_wav(
    sequence: &NoteEventSequence,
    output_path: &Path,
    sample_rate: u32,
) -> Result<AudioRenderSummary> {
    let total_duration_seconds = sequence.total_duration_seconds;
    let total_frames = (total_duration_seconds * sample_rate as f64).ceil() as usize;
    let mut left = vec![0.0f32; total_frames];
    let mut right = vec![0.0f32; total_frames];

    for event in &sequence.note_events {
        let start_frame = (event.start_seconds * sample_rate as f64).round() as usize;
        let end_frame = (event.end_seconds * sample_rate as f64).round() as usize;
        let duration_frames = end_frame.saturating_sub(start_frame);
        if duration_frames == 0 || start_frame >= total_frames {
            continue;
        }
        let end_frame = end_frame.min(total_frames);

        let (base_amplitude, left_gain, right_gain) = match event.part_index {
            1 => (0.12_f64, 0.72_f64, 0.46_f64),
            _ => (0.10_f64, 0.46_f64, 0.72_f64),
        };
        let attack_frames = ((sample_rate as f64 * 0.008).round() as usize).max(1);
        let release_frames = ((sample_rate as f64 * 0.02).round() as usize).max(1);
        let duration_frames = end_frame - start_frame;

        for frame in start_frame..end_frame {
            let local = frame - start_frame;
            let time = local as f64 / sample_rate as f64;
            let phase = 2.0 * PI * event.frequency_hz * time;
            let envelope = envelope(local, duration_frames, attack_frames, release_frames);
            let waveform = phase.sin() + 0.35 * (2.0 * phase).sin() + 0.15 * (3.0 * phase).sin();
            let sample = (base_amplitude * envelope * waveform) as f32;
            left[frame] += sample * left_gain as f32;
            right[frame] += sample * right_gain as f32;
        }
    }

    let peak = left
        .iter()
        .chain(right.iter())
        .map(|sample| sample.abs())
        .fold(0.0_f32, f32::max);
    let normalization_gain = if peak > 0.95 { 0.95 / peak as f64 } else { 1.0 };

    let spec = WavSpec {
        channels: 2,
        sample_rate,
        bits_per_sample: 16,
        sample_format: SampleFormat::Int,
    };
    let mut writer = WavWriter::create(output_path, spec)
        .with_context(|| format!("failed to create {}", output_path.display()))?;
    for frame in 0..total_frames {
        let left_sample = (left[frame] as f64 * normalization_gain).clamp(-1.0, 1.0);
        let right_sample = (right[frame] as f64 * normalization_gain).clamp(-1.0, 1.0);
        writer.write_sample(float_to_i16(left_sample))?;
        writer.write_sample(float_to_i16(right_sample))?;
    }
    writer.finalize()?;

    Ok(AudioRenderSummary {
        path: output_path
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_else(|| OFFLINE_AUDIO_FILE.to_string()),
        sample_rate,
        channels: 2,
        frames: total_frames as u32,
        duration_seconds: round6(total_duration_seconds),
        peak_amplitude: round6((peak as f64 * normalization_gain).min(1.0)),
        normalization_gain: round6(normalization_gain),
    })
}

pub fn build_validation_report(
    config: &CliConfig,
    contracts: &LoadedContracts,
    realization: &RealizedFragmentSequence,
    note_events: &NoteEventSequence,
    replay_matches: bool,
    replay_note_events_match: bool,
    audio_summary: Option<&AudioRenderSummary>,
) -> M1ValidationReport {
    let mut errors = Vec::new();
    let mut warnings = Vec::new();
    let mut checks = Vec::new();
    let expected_positions = &contracts.rules.position_labels;
    let actual_positions: Vec<String> = realization
        .fragments
        .iter()
        .map(|step| step.position_label.clone())
        .collect();
    let selector_domain_valid = config
        .rolls
        .iter()
        .all(|value| contracts.rules.selector.allowed_values.contains(value));
    if !selector_domain_valid {
        errors.push("selector domain check failed".to_string());
    }

    let actual_fragments: Vec<u16> = realization
        .fragments
        .iter()
        .map(|step| step.fragment_id)
        .collect();
    let expected_fragments = contracts
        .rules
        .position_labels
        .iter()
        .zip(config.rolls.iter())
        .map(|(label, roll)| {
            contracts
                .rules
                .columns
                .get(label)
                .and_then(|column| column.fragment_ids_by_roll.get(&roll.to_string()))
                .copied()
                .unwrap_or_default()
        })
        .collect::<Vec<u16>>();
    let rule_consistency = actual_fragments == expected_fragments;
    if !rule_consistency {
        errors.push("realized fragment sequence diverges from rules.json".to_string());
    }

    let duration_closure = note_events
        .note_events
        .iter()
        .map(|event| event.end_quarter_length)
        .fold(0.0_f64, f64::max)
        <= realization.total_duration_quarter_length + 1e-9;
    if !duration_closure {
        errors.push("note-event sequence overruns the realized timeline".to_string());
    }

    if note_events.note_events.is_empty() {
        errors.push("note-event sequence is empty".to_string());
    }
    if !replay_matches || !replay_note_events_match {
        errors.push("deterministic replay check failed".to_string());
    }

    if matches!(config.command, CommandKind::Realize) {
        warnings.push(
            "render-audio was not requested; offline_audio.wav is absent in this artifact set"
                .to_string(),
        );
    }
    if audio_summary.is_none() && matches!(config.command, CommandKind::RenderAudio) {
        errors.push("render-audio command did not produce offline_audio.wav".to_string());
    }

    checks.push(validation_check(
        "selector_input_length",
        config.rolls.len() == POSITION_COUNT,
        serde_json::json!({
            "expected_selector_count": POSITION_COUNT,
            "actual_selector_count": config.rolls.len(),
        }),
        &mut errors,
        "selector count must equal 16",
    ));
    checks.push(validation_check(
        "selector_domain",
        selector_domain_valid,
        serde_json::json!({
            "allowed_values": contracts.rules.selector.allowed_values,
            "actual_values": config.rolls,
        }),
        &mut errors,
        "selector values must remain in the inclusive range 2..12",
    ));
    checks.push(validation_check(
        "position_order",
        actual_positions == *expected_positions,
        serde_json::json!({
            "expected_positions": expected_positions,
            "actual_positions": actual_positions,
        }),
        &mut errors,
        "realized positions must remain in the canonical A1..B8 order",
    ));
    checks.push(validation_check(
        "fragment_rule_consistency",
        rule_consistency,
        serde_json::json!({
            "expected_fragments": expected_fragments,
            "actual_fragments": actual_fragments,
        }),
        &mut errors,
        "realized fragments must match rules.json",
    ));
    checks.push(validation_check(
        "deterministic_replay",
        replay_matches && replay_note_events_match,
        serde_json::json!({
            "fragment_sequence_replayed_identically": replay_matches,
            "note_events_replayed_identically": replay_note_events_match,
        }),
        &mut errors,
        "same input must realize and replay identically",
    ));
    checks.push(validation_check(
        "note_event_presence",
        !note_events.note_events.is_empty(),
        serde_json::json!({
            "note_event_count": note_events.note_events.len(),
            "distinct_pitch_count": note_events.summary.distinct_pitch_count,
        }),
        &mut errors,
        "note-event sequence must not be empty",
    ));
    checks.push(validation_check(
        "duration_closure",
        duration_closure,
        serde_json::json!({
            "realized_duration_quarter_length": realization.total_duration_quarter_length,
            "latest_note_end_quarter_length": note_events.note_events.iter().map(|event| event.end_quarter_length).fold(0.0_f64, f64::max),
        }),
        &mut errors,
        "note events must stay within the realized duration",
    ));
    checks.push(ValidationCheck {
        check_id: "offline_audio_output".to_string(),
        status: if audio_summary.is_some() {
            "passed".to_string()
        } else if matches!(config.command, CommandKind::Realize) {
            "warning".to_string()
        } else {
            "failed".to_string()
        },
        details: serde_json::to_value(audio_summary).unwrap_or_else(|_| serde_json::json!(null)),
    });

    let checks_failed = checks
        .iter()
        .filter(|check| check.status == "failed")
        .count();
    let checks_passed = checks
        .iter()
        .filter(|check| check.status == "passed")
        .count();

    M1ValidationReport {
        work_id: config.work_id.clone(),
        stage: "stage5_m1_runtime".to_string(),
        status: if checks_failed == 0 {
            "passed"
        } else {
            "failed"
        }
        .to_string(),
        command: command_name(&config.command).to_string(),
        input_rolls: config.rolls.clone(),
        checks,
        errors,
        warnings,
        summary: ValidationSummary {
            selector_count: config.rolls.len(),
            fragment_count: realization.fragments.len(),
            note_event_count: note_events.note_events.len(),
            total_duration_quarter_length: realization.total_duration_quarter_length,
            total_duration_seconds: realization.total_duration_seconds,
            tempo_bpm: config.tempo_bpm,
            sample_rate: config.sample_rate,
            checks_passed,
            checks_failed,
            audio_frames: audio_summary.map(|summary| summary.frames),
            peak_amplitude: audio_summary.map(|summary| summary.peak_amplitude),
        },
        output_files: OutputFiles {
            render_request: RENDER_REQUEST_FILE.to_string(),
            realized_fragment_sequence: REALIZED_FRAGMENT_SEQUENCE_FILE.to_string(),
            note_event_sequence: NOTE_EVENT_SEQUENCE_FILE.to_string(),
            validation_report: M1_VALIDATION_REPORT_FILE.to_string(),
            offline_audio: audio_summary.map(|summary| summary.path.clone()),
        },
    }
}

fn validation_check(
    check_id: &str,
    passed: bool,
    details: serde_json::Value,
    errors: &mut Vec<String>,
    message: &str,
) -> ValidationCheck {
    if !passed {
        errors.push(message.to_string());
    }
    ValidationCheck {
        check_id: check_id.to_string(),
        status: if passed {
            "passed".to_string()
        } else {
            "failed".to_string()
        },
        details,
    }
}

fn print_summary(config: &CliConfig, artifacts: &ArtifactPaths) {
    println!("command: {}", command_name(&config.command));
    println!("work: {}", config.work_id);
    println!("rolls: {}", format_rolls(&config.rolls));
    println!("output_dir: {}", artifacts.output_dir.display());
    println!(
        "artifacts: {}, {}, {}, {}",
        artifacts.render_request.display(),
        artifacts.realized_fragment_sequence.display(),
        artifacts.note_event_sequence.display(),
        artifacts.validation_report.display()
    );
    if let Some(path) = &artifacts.offline_audio {
        println!("audio: {}", path.display());
    }
}

fn command_name(command: &CommandKind) -> &'static str {
    match command {
        CommandKind::Realize => "realize",
        CommandKind::RenderAudio => "render-audio",
    }
}

fn format_rolls(rolls: &[u8]) -> String {
    rolls
        .iter()
        .map(u8::to_string)
        .collect::<Vec<String>>()
        .join(",")
}

fn envelope(
    frame: usize,
    duration_frames: usize,
    attack_frames: usize,
    release_frames: usize,
) -> f64 {
    if duration_frames == 0 {
        return 0.0;
    }
    if frame < attack_frames {
        return frame as f64 / attack_frames as f64;
    }
    let release_start = duration_frames.saturating_sub(release_frames);
    if frame >= release_start {
        let remaining = duration_frames.saturating_sub(frame);
        return remaining.max(1) as f64 / release_frames.max(1) as f64;
    }
    1.0
}

fn float_to_i16(sample: f64) -> i16 {
    (sample * i16::MAX as f64).round() as i16
}

fn midi_to_frequency(midi: u8) -> f64 {
    440.0 * 2.0_f64.powf((midi as f64 - 69.0) / 12.0)
}

fn round6(value: f64) -> f64 {
    (value * 1_000_000.0).round() / 1_000_000.0
}

fn read_json<T>(path: &Path) -> Result<T>
where
    T: for<'de> Deserialize<'de>,
{
    let text =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    serde_json::from_str(&text).with_context(|| format!("failed to parse {}", path.display()))
}

fn write_json<T>(path: &Path, value: &T) -> Result<()>
where
    T: Serialize,
{
    let text = serde_json::to_string_pretty(value)?;
    fs::write(path, format!("{text}\n"))
        .with_context(|| format!("failed to write {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_rolls_requires_exactly_sixteen_values() {
        let error = parse_rolls("2,3,4").unwrap_err().to_string();
        assert!(error.contains("expected exactly 16 selector values"));
    }

    #[test]
    fn demo_rolls_realize_expected_fragments() {
        let contracts = load_contracts(CANONICAL_WORK_ID).unwrap();
        let realization = realize_sequence(&contracts, &DEMO_ROLLS, DEFAULT_TEMPO_BPM).unwrap();
        let fragment_ids: Vec<u16> = realization
            .fragments
            .iter()
            .map(|step| step.fragment_id)
            .collect();
        assert_eq!(
            fragment_ids,
            vec![70, 64, 160, 35, 117, 27, 49, 89, 93, 34, 175, 107, 134, 32, 159, 20]
        );
        assert_eq!(realization.total_duration_quarter_length, 24.0);
        assert_eq!(realization.total_duration_seconds, 12.0);
    }

    #[test]
    fn note_events_are_deterministic_for_demo_rolls() {
        let contracts = load_contracts(CANONICAL_WORK_ID).unwrap();
        let realization_a = realize_sequence(&contracts, &DEMO_ROLLS, DEFAULT_TEMPO_BPM).unwrap();
        let realization_b = realize_sequence(&contracts, &DEMO_ROLLS, DEFAULT_TEMPO_BPM).unwrap();
        let notes_a = build_note_event_sequence(
            &contracts,
            &realization_a,
            &DEMO_ROLLS,
            DEFAULT_TEMPO_BPM,
            DEFAULT_SAMPLE_RATE,
        )
        .unwrap();
        let notes_b = build_note_event_sequence(
            &contracts,
            &realization_b,
            &DEMO_ROLLS,
            DEFAULT_TEMPO_BPM,
            DEFAULT_SAMPLE_RATE,
        )
        .unwrap();
        assert_eq!(realization_a, realization_b);
        assert_eq!(notes_a, notes_b);
        assert!(!notes_a.note_events.is_empty());
    }
}
