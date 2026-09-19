"""Issue 64 offline acceptance; each invocation owns a fresh output directory."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import build_stage5_unique_stream as stage5
import build_stage6_video_render as render
from stage6_events import (ROOT, ORDER, build_contract, validate_contract, event_key,
                           response_policy, responses, state_at)

TOOLS = Path(__file__).resolve().parent


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def read(path):
    return json.loads(Path(path).read_text())


def run(command, root):
    command = list(map(str, command))
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with (root / 'commands.log').open('a') as log:
        log.write('$ ' + ' '.join(command) + '\n' + result.stdout + f'\nexit={result.returncode}\n')
    print('$', ' '.join(command), 'exit=', result.returncode, flush=True)
    if result.returncode:
        raise RuntimeError(result.stdout)
    return result.stdout


def prepare_source(root, name, rolls, loops):
    out = root / name
    args = argparse.Namespace(synth_profile=str(TOOLS.parent / 'runtime/config/stage5_default_synth_profile.json'),
                              soundfont=None, cargo_bin='cargo', work_id='mozart_dicegame_print_1790s',
                              loop_count=loops, analysis_window_ms=40, tempo_bpm=120,
                              sample_rate=16000, output_dir=str(out))
    rules = stage5.load_rules()
    selection = stage5.build_selection_payload(work_id=args.work_id, position_labels=rules['position_labels'],
                    allowed_values=rules['selector']['allowed_values'], rolls=rolls,
                    ledger_path=root / 'unused-ledger.json', played_unique_count=1, collision_retries=0)
    profile = stage5.load_soundscape_profile(stage5.DEFAULT_SOUNDSCAPE_PROFILE)
    registration = stage5.resolve_registration_choice(args=args, selection=selection, soundscape_profile=profile)
    assert registration is not None
    run(stage5.build_runtime_command(args, rolls, registration), root)
    stage5.augment_selection_artifact(out, selection)
    stage5.apply_soundscape_mix(artifact_dir=out, selection=read(out / 'combination_selection.json'),
                               soundscape_profile=profile, registration_choice=registration)
    return out


def combine(root, a, b):
    out = root / 'adjacent'
    shutil.copytree(a, out)
    plan, other = read(a / 'stream_loop_plan.json'), read(b / 'stream_loop_plan.json')
    offset = plan['total_duration_seconds']
    frame_offset = plan['total_duration_frames']
    for cycle in other['cycles']:
        cycle = dict(cycle, cycle_index=len(plan['cycles']) + 1)
        for field in ('start_seconds', 'end_seconds'):
            cycle[field] += offset
        for field in ('start_frame', 'end_frame'):
            cycle[field] += frame_offset
        plan['cycles'].append(cycle)
    plan['loop_count'] = len(plan['cycles'])
    plan['total_duration_seconds'] += other['total_duration_seconds']
    plan['total_duration_frames'] += other['total_duration_frames']
    save(out / 'stream_loop_plan.json', plan)
    realization = read(a / 'realized_fragment_sequence.json')
    realization['cycle_realizations'] = {'3': read(b / 'realized_fragment_sequence.json')}
    save(out / 'realized_fragment_sequence.json', realization)
    analysis = read(a / 'analysis_window_sequence.json')
    for window in read(b / 'analysis_window_sequence.json')['windows']:
        window = dict(window, window_index=len(analysis['windows']) + 1, cycle_index=3)
        for field in ('start_seconds', 'end_seconds', 'clock_seconds'):
            window[field] += offset
        for field in ('start_frame', 'end_frame', 'clock_frame'):
            window[field] += frame_offset
        analysis['windows'].append(window)
    analysis['total_duration_seconds'] = plan['total_duration_seconds'] + 0.8
    analysis['loop_count'] = 3
    save(out / 'analysis_window_sequence.json', analysis)
    selection = read(out / 'combination_selection.json')
    selection['combination_hold_cycles'] = 3
    save(out / 'combination_selection.json', selection)
    summary = read(out / 'artifact_summary.json')
    summary['audio_duration_seconds'] = analysis['total_duration_seconds']
    save(out / 'artifact_summary.json', summary)
    save(out / 'structural_events.json', build_contract([a, b], 0.8))
    return out


def rejects(contract, root):
    cases = [('negative', 'clock_seconds', -1), ('nan', 'clock_seconds', float('nan')),
             ('beyond', 'clock_seconds', contract['structural_duration_seconds'] + 0.1),
             ('type', 'type', 'unknown'), ('voice', 'voice_group', 'voice_group_1')]
    evidence = []
    for name, field, value in cases:
        invalid = deepcopy(contract)
        invalid['events'][0][field] = value
        try:
            validate_contract(invalid)
        except ValueError as error:
            assert field in str(error), str(error)
            evidence.append(dict(case=name, field=field, error=str(error)))
        else:
            raise AssertionError(f'{name} accepted')
    invalid = deepcopy(contract)
    invalid['events'][0], invalid['events'][-1] = invalid['events'][-1], invalid['events'][0]
    try:
        validate_contract(invalid)
    except ValueError as error:
        assert 'order' in str(error)
        evidence.append(dict(case='order', error=str(error)))
    else:
        raise AssertionError('out of order accepted')
    save(root / 'counterexamples.json', evidence)


def stub(source, output, root, *options):
    run([sys.executable, TOOLS / 'build_stage6_video_stub.py', source, output, *options], root)
    run([sys.executable, TOOLS / 'validate_stage6_video_stub.py', output], root)
    return read(output / 'video_stub_scene.json')


def check_l1(root, source, a, b):
    contract = read(source / 'structural_events.json')
    assert contract == build_contract([a, b], 0.8)
    counts = Counter(e['type'] for e in contract['events'])
    assert set(counts) == set(ORDER) and counts['combination_transition'] == 1
    assert next(e for e in contract['events'] if e['type'] == 'combination_transition')['clock_seconds'] == 24
    rejects(contract, root)
    scene = stub(source, root / 'stub', root)
    stub(source, root / 'stub-repeat', root)
    assert (root / 'stub/video_stub_scene.json').read_bytes() == (root / 'stub-repeat/video_stub_scene.json').read_bytes()
    print('L1 counts:', dict(counts), flush=True)
    save(root / 'event-counts.json', dict(counts))
    return scene


def check_l2(root, source, scene):
    contract = scene['structural_events']
    policy = response_policy({})
    dense = deepcopy(contract)
    dense['events'] += [dict(contract['events'][0], clock_seconds=0.01)]
    dense['events'].sort(key=event_key)
    validate_contract(dense)
    accepted = responses(dense, policy)
    assert len(dense['events']) == len(contract['events']) + 1
    last = {}
    for event in accepted:
        key = event['type'], event['voice_group']
        assert event['clock_seconds'] - last.get(key, -1) >= 0.25 - 1e-9
        last[key] = event['clock_seconds']
    assert len([e for e in accepted if e['clock_seconds'] == 0]) == 5
    frames = render.build_frame_sequence(scene)
    assert frames == render.build_frame_sequence(scene)
    assert max(f['structural_response']['intensity'] for f in frames['frames']) <= 0.18
    assert len({f['global_scale'] for f in frames['frames']}) > 10
    assert frames['frames'][-1]['structural_response']['intensity'] == 0
    disabled = stub(source, root / 'disabled', root, '--disable-events')
    event_path = source / 'structural_events.json'
    event_path.rename(source / 'saved-events.json')
    missing = stub(source, root / 'missing', root)
    save(event_path, dict(contract, events=[]))
    empty = stub(source, root / 'empty', root)
    reference = render.build_frame_sequence(disabled)
    assert reference == render.build_frame_sequence(missing) == render.build_frame_sequence(empty)
    base = render.build_base_canvas(disabled)
    for index in (0, 10, 100):
        frame = reference['frames'][index]
        assert render.render_frame_bytes(disabled, frame, base) == render.render_frame_bytes(missing, frame, base)
    save(event_path, dict(contract, schema_version=99))
    result = subprocess.run([sys.executable, str(TOOLS / 'build_stage6_video_stub.py'), str(source), str(root / 'broken')], capture_output=True, text=True)
    assert result.returncode != 0 and 'schema_version' in result.stderr
    save(root / 'malformed-input.json', dict(exit=result.returncode, stderr=result.stderr))
    (source / 'saved-events.json').replace(event_path)
    save(root / 'responses.json', accepted)
    save(root / 'frame-determinism.json', dict(frame_count=len(frames['frames']), fallback_equal=True))
    print('L2 dense/fallback/deterministic frames passed', flush=True)


def probe(path, root, width, height, frames):
    data = json.loads(run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', path], root))
    video = data['streams'][0]
    assert video['width'] == width and video['height'] == height
    assert video['avg_frame_rate'] == '30/1'
    assert int(video['nb_read_frames']) == frames
    assert abs(float(data['format']['duration']) - frames / 30) < 0.05
    run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'null', '-'], root)
    save(path.with_suffix('.probe.json'), data)


def acceptance(root, source, scene):
    make = ['make', '-C', 'src/musikalisches', f'STAGE6_SOURCE_DIR={source}',
            f'VIDEO_STUB_OUT={root / "stub"}', f'VIDEO_RENDER_OUT={root / "render"}']
    for target in ('stage6-scene-profile-check-all', 'stage6-video-stub', 'stage6-video-check',
                   'stage6-video-render', 'stage6-video-render-check'):
        run([*make, target], root)
    out = root / 'render'
    frames = round(scene['summary']['total_duration_seconds'] * 30)
    probe(out / 'offline_preview.mp4', root, 1280, 720, frames)
    # Exact 9:16 with even encoding dimensions: crop full 405x720 safe region,
    # then scale uniformly to 432x768. No content is discarded to force evenness.
    safe = scene['short_safe_layout']
    crop = f"crop={safe['width']}:{safe['height']}:{safe['x']}:{safe['y']}:exact=1,scale=432:768"
    run(['ffmpeg', '-v', 'error', '-y', '-i', out / 'offline_preview.mp4', '-vf', crop,
         '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', out / 'short-safe.mp4'], root)
    probe(out / 'short-safe.mp4', root, 432, 768, frames)
    run(['ffmpeg', '-v', 'error', '-y', '-i', out / 'video_render_poster.ppm', '-frames:v', '1', out / 'landscape.png'], root)
    run(['ffmpeg', '-v', 'error', '-y', '-i', out / 'video_render_poster.ppm', '-vf', crop, '-frames:v', '1', out / 'short-safe.png'], root)
    for name, clock in [('downbeat', 0.133333), ('fragment', 0.9), ('transition', 24.133333), ('tail', 36.6)]:
        for layout, video in [('wide', 'offline_preview.mp4'), ('short', 'short-safe.mp4')]:
            run(['ffmpeg', '-v', 'error', '-y', '-ss', str(clock), '-i', out / video, '-frames:v', '1', out / f'{name}-{layout}.png'], root)
    save(root / 'acceptance.json', dict(output=str(out), crop=safe, encoded_short=[432, 768],
                                       fps=30, frames=frames, duration=frames / 30))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('level', choices=['l1', 'l2', 'l3'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    parent = ROOT / 'ops/out'
    parent.mkdir(parents=True, exist_ok=True)
    root = args.output or Path(tempfile.mkdtemp(prefix='issue64-events-', dir=parent))
    root.mkdir(parents=True, exist_ok=True)
    print('OUTPUT:', root, flush=True)
    a = prepare_source(root, 'a', [2] * 16, 2)
    b = prepare_source(root, 'b', [12] * 16, 1)
    source = combine(root, a, b)
    scene = check_l1(root, source, a, b)
    if args.level in ('l2', 'l3'):
        check_l2(root, source, scene)
    if args.level == 'l3':
        acceptance(root, source, scene)
    print('PASS', args.level, root, flush=True)


if __name__ == '__main__':
    main()
