"""Read-only Stage5 structure -> versioned Stage6 events (no audio inference)."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INGEST = ROOT / 'docs/study/music_dice_games_package/mozart_dicegame_print_1790s/ingest'
ORDER = {name: index for index, name in enumerate(
    ('combination_transition', 'fragment_boundary', 'bar', 'downbeat'))}
DEFAULT_RESPONSE = dict(min_interval_seconds=0.25, energy_threshold=0.05,
                        attack_seconds=0.12, release_seconds=0.4)


def load(path):
    return json.loads(Path(path).read_text())


def event_key(event):
    return (event['clock_seconds'], ORDER[event['type']],
            event['voice_group'] or '', event['source_id'])


def number(value, field, minimum: float = 0):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{field}: expected finite number >= {minimum}')
    return value


def validate_event(event, index, duration, groups):
    prefix = f'events[{index}]'
    if not isinstance(event, dict):
        raise ValueError(f'{prefix}: expected object')
    for key in ('clock_seconds', 'type', 'source_id', 'voice_group'):
        if key not in event:
            raise ValueError(f'{prefix}.{key}: required')
    clock = number(event['clock_seconds'], f'{prefix}.clock_seconds')
    if clock >= duration:
        raise ValueError(f'{prefix}.clock_seconds: must precede structural end {duration}')
    if event['type'] not in ORDER:
        raise ValueError(f'{prefix}.type: unknown type')
    if not isinstance(event['source_id'], str) or not event['source_id']:
        raise ValueError(f'{prefix}.source_id: nonempty string required')
    group = event['voice_group']
    if group is not None and (not isinstance(group, str) or group not in groups):
        raise ValueError(f'{prefix}.voice_group: unknown part-N')
    if group is not None:
        if event['type'] != 'downbeat':
            raise ValueError(f'{prefix}.voice_group: global structure must be null')
        energy = number(event.get('energy'), f'{prefix}.energy')
        if energy > 1:
            raise ValueError(f'{prefix}.energy: must be <= 1')
        if event.get('energy_source') != 'note_event_activity_proxy':
            raise ValueError(f'{prefix}.energy_source: expected note_event_activity_proxy')
    if 'end_seconds' in event:
        end = number(event['end_seconds'], f'{prefix}.end_seconds', clock)
        if end > duration:
            raise ValueError(f'{prefix}.end_seconds: exceeds structure')


def validate_contract(contract):
    if not isinstance(contract, dict) or contract.get('schema_version') != 1:
        raise ValueError('structural_events.schema_version: expected 1')
    duration = number(contract.get('structural_duration_seconds'), 'structural_duration_seconds')
    number(contract.get('render_duration_seconds'), 'render_duration_seconds', duration)
    groups = contract.get('voice_groups')
    if not isinstance(groups, list) or any(not isinstance(g, str) or not re.fullmatch(r'part-[1-9][0-9]*', g) for g in groups):
        raise ValueError('voice_groups: expected part-N array')
    events = contract.get('events')
    if not isinstance(events, list):
        raise ValueError('events: expected array')
    previous = None
    for index, event in enumerate(events):
        validate_event(event, index, duration, groups)
        key = event_key(event)
        if previous is not None and key < previous:
            raise ValueError(f'events[{index}].clock_seconds/type/voice_group/source_id: order violation')
        previous = key
    return contract


def fragment_events(realized, notes, cycle, combination, measures):
    events = []
    tempo = number(realized['tempo_bpm'], 'tempo_bpm', 1)
    for fragment in realized['fragments']:
        measure = measures.get(fragment['source_measure_sequence_index'])
        if not measure or measure['runtime_fragment_id'] != fragment['fragment_id']:
            raise ValueError('fragment.source_measure_sequence_index: frozen measure mismatch')
        numerator, denominator = map(int, measure['time_signature'].split('/'))
        quarters = numerator * 4 / denominator
        if not math.isclose(quarters, measure['duration_quarter_length']) or not math.isclose(quarters, fragment['duration_quarter_length']):
            raise ValueError('fragment.duration_quarter_length: incomplete frozen measure')
        start = cycle['start_seconds'] + fragment['start_seconds']
        end = cycle['start_seconds'] + fragment['end_seconds']
        if not math.isclose(end - start, quarters * 60 / tempo, abs_tol=1e-6):
            raise ValueError('fragment.end_seconds: tempo/measure duration mismatch')
        common = dict(clock_seconds=round(start, 6), voice_group=None,
                      source_id=f"cycle-{cycle['cycle_index']}/measure-{fragment['source_measure_sequence_index']}",
                      combination_id=combination, position_label=fragment['position_label'],
                      selector_value=fragment['selector_value'], end_seconds=round(end, 6),
                      provenance=dict(measure_number=measure['source_measure_number'],
                                      time_signature=measure['time_signature'], tempo_bpm=tempo,
                                      source='ingest/measures.json + realized_fragment_sequence.json'))
        for kind in ('fragment_boundary', 'bar', 'downbeat'):
            events.append(dict(common, type=kind))
        for group in notes['voice_groups']:
            group_id = group['voice_group_id']
            active = any(n['step_index'] == fragment['step_index'] and n['voice_group_id'] == group_id
                         for n in notes['note_events'])
            events.append(dict(common, type='downbeat', voice_group=group_id,
                               energy=float(active), energy_source='note_event_activity_proxy'))
    return events


def build_contract(source_dirs, tail_seconds: float = 0):
    measures = {m['source_measure_sequence_index']: m for m in load(INGEST / 'measures.json')['measures']}
    events, groups, offset, last, cycle_index = [], set(), 0.0, None, 0
    for source in source_dirs:
        source = Path(source)
        realized = load(source / 'realized_fragment_sequence.json')
        notes = load(source / 'note_event_sequence.json')
        plan = load(source / 'stream_loop_plan.json')
        combination = ','.join(map(str, realized['rolls']))
        groups.update(g['voice_group_id'] for g in notes['voice_groups'])
        for original in plan['cycles']:
            cycle_index += 1
            cycle = dict(original, cycle_index=cycle_index,
                         start_seconds=offset + original['start_seconds'])
            if last is not None and last != combination:
                events.append(dict(clock_seconds=round(cycle['start_seconds'], 6),
                                   type='combination_transition', voice_group=None,
                                   source_id=f'cycle-{cycle_index}', combination_id=combination))
            events.extend(fragment_events(realized, notes, cycle, combination, measures))
            last = combination
        offset += plan['cycles'][-1]['end_seconds']
    return validate_contract(dict(schema_version=1, structural_duration_seconds=round(offset, 6),
                                  render_duration_seconds=round(offset + number(tail_seconds, 'tail_seconds'), 6),
                                  voice_groups=sorted(groups), events=sorted(events, key=event_key)))


def response_policy(profile):
    policy = dict(DEFAULT_RESPONSE, **profile.get('event_response', {}))
    for name, value in policy.items():
        if name not in DEFAULT_RESPONSE:
            raise ValueError(f'event_response.{name}: unknown field')
        number(value, f'event_response.{name}', 0.000001 if name.endswith('seconds') else 0)
    if policy['energy_threshold'] > 1:
        raise ValueError('event_response.energy_threshold: must be <= 1')
    return policy


def responses(contract, policy):
    last, accepted = {}, []
    for event in contract['events']:
        key = (event['type'], event['voice_group'])
        if event['voice_group'] is not None and event['energy'] < policy['energy_threshold']:
            continue
        if event['clock_seconds'] - last.get(key, -math.inf) + 1e-9 < policy['min_interval_seconds']:
            continue
        accepted.append(event)
        last[key] = event['clock_seconds']
    return accepted


def state_at(contract, accepted, clock, policy):
    state: dict = dict(intensity=0.0, downbeat=0.0, bar=0.0, transition=0.0,
                 combination_id=None, fragment_label=None, voices={})
    for event in contract['events']:
        if event['clock_seconds'] > clock:
            break
        state['combination_id'] = event.get('combination_id', state['combination_id'])
        if event['type'] == 'fragment_boundary':
            state['fragment_label'] = f"{event['position_label']} = {event['selector_value']}"
    for event in accepted:
        age = clock - event['clock_seconds']
        attack, release = policy['attack_seconds'], policy['release_seconds']
        if not 0 <= age < attack + release:
            continue
        value = age / attack if age < attack else 1 - (age - attack) / release
        value = (value * value * (3 - 2 * value)) * 0.18
        state['intensity'] = max(state['intensity'], value)
        if event['voice_group']:
            state['voices'][event['voice_group']] = max(state['voices'].get(event['voice_group'], 0), value)
        else:
            field = {'downbeat': 'downbeat', 'bar': 'bar', 'combination_transition': 'transition'}.get(event['type'])
            if field:
                state[field] = max(state[field], value)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tail-seconds', type=float, default=0)
    args = parser.parse_args()
    args.output.write_text(json.dumps(build_contract(args.sources, args.tail_seconds), indent=2) + '\n')


if __name__ == '__main__':
    main()
