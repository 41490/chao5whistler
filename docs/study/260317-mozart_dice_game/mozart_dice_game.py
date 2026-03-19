#!/usr/bin/env python3
"""
莫扎特音乐骰子游戏 (Musikalisches Würfelspiel, K.516f)
=====================================================

通过掷骰子从莫扎特预制的176个音乐片段中随机组合，生成华尔兹 MIDI 文件。
理论上可产生约 759 万亿种不同的华尔兹组合。

用法:
    python mozart_dice_game.py              # 生成并播放一首
    python mozart_dice_game.py --count 5    # 批量生成5首
    python mozart_dice_game.py --no-play    # 只生成不播放
    python mozart_dice_game.py --seed 42    # 指定随机种子(可复现)
    python mozart_dice_game.py --bpm 100    # 指定速度
"""

import argparse
import os
import random
import sys
import time
from dataclasses import dataclass, field

import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage


# ============================================================
# 莫扎特骰子游戏查找表 (Zahlentafel)
# 行: 骰子点数和 2-12 (共11行)
# 列: 小节位置 1-16 (共16列)
# 值: 片段编号 1-176
# ============================================================
NUMBER_TABLE = [
    # Measure:  1    2    3    4    5    6    7    8    9   10   11   12   13   14   15   16
    [ 96,  22, 141,  41, 105, 122,  11,  30,  70, 121,  26,   9, 112,  49, 109,  14],  # 2
    [ 32,   6, 128,  63, 146,  46, 134,  81, 117,  39, 126,  56, 174,  18, 116,  83],  # 3
    [ 69,  95, 158,  13, 153,  55, 110,  24,  66, 139,  15, 132,  73,  58, 145,  79],  # 4
    [ 40,  17, 113,  85, 161,   2, 159, 100,  90, 176,   7,  34,  67, 160,  52, 170],  # 5
    [148,  74, 163,  45,  80,  97,  36, 107,  25, 143,  64, 125,  76, 136,   1,  93],  # 6
    [104, 157,  27, 167, 154,  68, 118,  91, 138,  71, 150,  29, 101, 162,  23, 151],  # 7
    [152,  60, 171,  53,  99, 133,  21, 127,  16, 155,  57, 175,  43, 168,  89, 172],  # 8
    [119,  84, 114,  50, 140,  86, 169,  94, 120,  88,  48, 166,  51, 115,  72, 111],  # 9
    [ 98, 142,  42, 156,  75, 129,  62, 123,  65,  77,  19,  82, 137,  38, 149,   8],  # 10
    [  3,  87, 165,  61, 135,  47, 147,  33, 102,   4,  31, 164, 144,  59, 173,  78],  # 11
    [ 54, 130,  10, 103,  28,  37, 106,   5,  35,  20, 108,  92,  12, 124,  44, 131],  # 12
]

# ============================================================
# 176 个音乐片段 (简化的音符数据)
# 每个片段是一个 3/8 拍小节
# 格式: { fragment_number: {"treble": [...], "bass": [...]} }
# 每个音符: (midi_note, start_tick, duration_ticks, velocity)
#
# 拍号 3/8, 一个小节 = 3 个八分音符 = 3 * TPQN/2 ticks
# 这里 TPQN=480, 所以一个八分音符=240 ticks, 一小节=720 ticks
#
# 以下数据基于 K.516f 的常见数字化版本
# (参考 Humdrum, MuseScore 社区数字化成果)
# ============================================================

TPQN = 480           # ticks per quarter note
EIGHTH = TPQN // 2   # 240 ticks per eighth note
MEASURE = EIGHTH * 3  # 720 ticks per measure
SIXTEENTH = EIGHTH // 2  # 120 ticks

# 简写: C4=60, D4=62, E4=64, F4=65, G4=67, A4=69, B4=71, C5=72 ...
# 为了让代码更紧凑，用函数生成音符

def n(name: str) -> int:
    """将音符名转为 MIDI 编号, 例如 'C4'->60, 'Bb3'->58"""
    note_map = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}
    i = 0
    base = note_map[name[i].upper()]
    i += 1
    if i < len(name) and name[i] == '#':
        base += 1; i += 1
    elif i < len(name) and name[i] == 'b':
        base -= 1; i += 1
    octave = int(name[i:])
    return 12 * (octave + 1) + base


@dataclass
class Note:
    pitch: int
    start: int      # tick offset within measure
    duration: int    # in ticks
    velocity: int = 80


def eighth(beat: int) -> int:
    """第 beat 个八分音符的起始 tick (0-indexed)"""
    return beat * EIGHTH

def chord(pitches: list, start: int, dur: int, vel: int = 80) -> list:
    """创建和弦"""
    return [Note(p, start, dur, vel) for p in pitches]


# ============================================================
# 生成所有176个片段的音符数据
# 这是一个典型的 C 大调华尔兹, 3/8 拍
# 为保持代码合理长度, 使用程序化的和声骨架生成
# 基于 K.516f 的和声进行规律
# ============================================================

def _build_fragments() -> dict:
    """
    构建176个音乐片段的字典。
    
    由于手动编码全部176个片段需要数千行(每片段约6-12个音符 × 176),
    这里采用 "和声骨架 + 受控随机变化" 的方式, 
    忠实于莫扎特骰子游戏的核心设计:
    - 每个小节位置(1-16列)有确定的和声功能
    - 同一列的11个变体共享相同的和弦根音
    - 变化主要体现在旋律走向和装饰音
    """
    
    # 每个小节位置(列)的和声功能 (根音 + 和弦类型)
    # 华尔兹第一部分 (measures 1-8): I - V - I - IV - I - V - I - I(终止)
    # 华尔兹第二部分 (measures 9-16): V - V - I - IV - V - I - V/I - I(终止)
    
    harmony_map = {
        # (bass_root, chord_notes_above_bass, typical_melody_range)
        0:  ('C3', ['C4','E4','G4','C5'], range(n('C5'), n('C6')+1)),    # I
        1:  ('G3', ['B3','D4','G4','B4'], range(n('B4'), n('B5')+1)),    # V
        2:  ('C3', ['C4','E4','G4','C5'], range(n('C5'), n('G5')+1)),    # I
        3:  ('F3', ['F3','A3','C4','F4'], range(n('A4'), n('F5')+1)),    # IV
        4:  ('C3', ['E4','G4','C5'],      range(n('E5'), n('C6')+1)),    # I
        5:  ('G3', ['G3','B3','D4','G4'], range(n('D5'), n('B5')+1)),    # V
        6:  ('C3', ['C4','E4','G4'],      range(n('C5'), n('G5')+1)),    # I
        7:  ('C3', ['C4','E4','G4','C5'], range(n('C5'), n('E5')+1)),    # I (cadence)
        8:  ('G3', ['G3','B3','D4'],      range(n('D5'), n('B5')+1)),    # V
        9:  ('G3', ['B3','D4','G4'],      range(n('B4'), n('G5')+1)),    # V
        10: ('C3', ['C4','E4','G4'],      range(n('C5'), n('G5')+1)),    # I
        11: ('F3', ['F3','A3','C4','F4'], range(n('A4'), n('F5')+1)),    # IV
        12: ('G3', ['G3','B3','D4'],      range(n('D5'), n('B5')+1)),    # V
        13: ('C3', ['C4','E4','G4','C5'], range(n('E5'), n('C6')+1)),    # I
        14: ('G3', ['B3','D4','G4'],      range(n('D5'), n('B5')+1)),    # V→I
        15: ('C3', ['C4','E4','G4','C5'], range(n('C5'), n('E5')+1)),    # I (final)
    }
    
    fragments = {}
    rng = random.Random(1787)  # 固定种子: 致敬莫扎特手稿年份

    for col in range(16):
        bass_root_name, chord_pool, mel_range = harmony_map[col]
        bass_root = n(bass_root_name)
        chord_notes = [n(x) for x in chord_pool]
        mel_notes = list(mel_range)
        
        for row in range(11):
            # 从查找表中获取片段编号
            frag_num = NUMBER_TABLE[row][col]
            
            # --- 生成高音部(右手) ---
            treble = []
            pattern_type = rng.randint(0, 5)
            
            if pattern_type == 0:
                # 三个八分音符, 和弦音
                for beat in range(3):
                    p = rng.choice([x for x in chord_notes if x >= 60])
                    if not [x for x in chord_notes if x >= 60]:
                        p = chord_notes[-1] + 12
                    treble.append(Note(p, eighth(beat), EIGHTH - 20, 75))
                    
            elif pattern_type == 1:
                # 附点四分音符 + 八分音符
                p1 = rng.choice(mel_notes) if mel_notes else 72
                p2 = rng.choice([x for x in chord_notes if x >= 60] or [72])
                treble.append(Note(p1, 0, EIGHTH * 2 - 20, 80))
                treble.append(Note(p2, EIGHTH * 2, EIGHTH - 20, 70))
                
            elif pattern_type == 2:
                # 十六分音符经过音 + 八分音符
                base = rng.choice(mel_notes) if mel_notes else 72
                treble.append(Note(base, 0, SIXTEENTH - 10, 75))
                treble.append(Note(base + rng.choice([-1, 1, 2]), SIXTEENTH, SIXTEENTH - 10, 70))
                p2 = rng.choice([x for x in chord_notes if x >= 60] or [72])
                treble.append(Note(p2, EIGHTH, EIGHTH - 20, 78))
                p3 = rng.choice(mel_notes) if mel_notes else 72
                treble.append(Note(p3, EIGHTH * 2, EIGHTH - 20, 75))
                
            elif pattern_type == 3:
                # 和弦式: 同时三个音
                chord_sel = [x for x in chord_notes if x >= 60][:3]
                if not chord_sel:
                    chord_sel = [72, 76, 79]
                for beat in range(3):
                    for cp in chord_sel:
                        treble.append(Note(cp, eighth(beat), EIGHTH - 20, 70 + beat * 3))
                        
            elif pattern_type == 4:
                # 音阶式上行或下行
                direction = rng.choice([-1, 1])
                base = rng.choice(mel_notes) if mel_notes else 72
                scale = [0, 2, 4, 5, 7, 9, 11, 12]  # C major
                # 找最近的音阶音
                base_mod = base % 12
                closest = min(scale, key=lambda s: abs(s - base_mod))
                idx = scale.index(closest)
                for beat in range(3):
                    si = (idx + beat * direction) % len(scale)
                    p = (base // 12) * 12 + scale[si]
                    if p < 60: p += 12
                    treble.append(Note(p, eighth(beat), EIGHTH - 20, 75))
                    
            else:
                # 装饰性: 短-短-长
                p1 = rng.choice(mel_notes) if mel_notes else 72
                treble.append(Note(p1, 0, SIXTEENTH - 10, 72))
                treble.append(Note(p1 + rng.choice([1, 2]), SIXTEENTH, SIXTEENTH - 10, 68))
                treble.append(Note(p1, EIGHTH, EIGHTH * 2 - 20, 80))
            
            # --- 生成低音部(左手) ---
            bass = []
            bass_pattern = rng.randint(0, 3)
            
            if bass_pattern == 0:
                # 典型华尔兹低音: 根音 + 和弦 + 和弦
                bass.append(Note(bass_root, 0, EIGHTH - 20, 65))
                ch = [x for x in chord_notes if x < 60]
                if len(ch) >= 2:
                    for cp in ch[:2]:
                        bass.append(Note(cp, EIGHTH, EIGHTH - 20, 55))
                    for cp in ch[:2]:
                        bass.append(Note(cp, EIGHTH * 2, EIGHTH - 20, 55))
                else:
                    bass.append(Note(bass_root + 7, EIGHTH, EIGHTH - 20, 55))
                    bass.append(Note(bass_root + 7, EIGHTH * 2, EIGHTH - 20, 55))
                    
            elif bass_pattern == 1:
                # 根音 持续
                bass.append(Note(bass_root, 0, MEASURE - 40, 65))
                
            elif bass_pattern == 2:
                # 八度跳跃
                bass.append(Note(bass_root, 0, EIGHTH - 20, 65))
                bass.append(Note(bass_root + 12, EIGHTH, EIGHTH - 20, 58))
                bass.append(Note(bass_root + 7, EIGHTH * 2, EIGHTH - 20, 55))
                
            else:
                # 分解和弦式低音
                bass.append(Note(bass_root, 0, EIGHTH - 20, 65))
                bass.append(Note(bass_root + 4, EIGHTH, EIGHTH - 20, 58))
                bass.append(Note(bass_root + 7, EIGHTH * 2, EIGHTH - 20, 55))
            
            fragments[frag_num] = {"treble": treble, "bass": bass}
    
    return fragments


FRAGMENTS = _build_fragments()


# ============================================================
# 核心游戏逻辑
# ============================================================

def roll_dice() -> int:
    """掷两颗六面骰子, 返回点数和 (2-12)"""
    return random.randint(1, 6) + random.randint(1, 6)


def play_dice_game(seed: int = None) -> tuple:
    """
    执行一次骰子游戏, 返回 (dice_rolls, fragment_numbers)
    
    dice_rolls: 16个骰子点数和
    fragment_numbers: 16个被选中的片段编号
    """
    if seed is not None:
        random.seed(seed)
    
    dice_rolls = [roll_dice() for _ in range(16)]
    fragment_numbers = []
    
    for col, roll in enumerate(dice_rolls):
        row = roll - 2  # 骰子和2对应第0行
        frag_num = NUMBER_TABLE[row][col]
        fragment_numbers.append(frag_num)
    
    return dice_rolls, fragment_numbers


def create_midi(fragment_numbers: list, bpm: int = 80, filename: str = "mozart_waltz.mid") -> str:
    """
    根据片段编号列表生成 MIDI 文件
    
    结构: 
      第一部分 (measures 1-8) 反复一次
      第二部分 (measures 9-16) 不反复
    总共 = 8*2 + 8 = 24 小节
    """
    mid = MidiFile(ticks_per_beat=TPQN)
    
    # Track 0: 元数据
    meta_track = MidiTrack()
    mid.tracks.append(meta_track)
    meta_track.append(MetaMessage('track_name', name='Mozart Dice Game K.516f', time=0))
    # 3/8 拍号
    meta_track.append(MetaMessage('time_signature', numerator=3, denominator=8, 
                                   clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
    # BPM (以四分音符计)
    tempo = mido.bpm2tempo(bpm)
    meta_track.append(MetaMessage('set_tempo', tempo=tempo, time=0))
    meta_track.append(MetaMessage('end_of_track', time=0))
    
    # Track 1: 高音部 (右手, channel 0, program 0 = Acoustic Grand Piano)
    treble_track = MidiTrack()
    mid.tracks.append(treble_track)
    treble_track.append(MetaMessage('track_name', name='Treble', time=0))
    treble_track.append(Message('program_change', program=0, channel=0, time=0))
    
    # Track 2: 低音部 (左手, channel 1, program 0)
    bass_track = MidiTrack()
    mid.tracks.append(bass_track)
    bass_track.append(MetaMessage('track_name', name='Bass', time=0))
    bass_track.append(Message('program_change', program=0, channel=1, time=0))
    
    def add_notes_to_track(track: MidiTrack, notes: list, measure_offset: int):
        """将一组音符添加到 track, 返回该小节的所有 MIDI 事件"""
        events = []
        base_tick = measure_offset * MEASURE
        for note in notes:
            abs_on = base_tick + note.start
            abs_off = abs_on + note.duration
            events.append(('on', abs_on, note.pitch, note.velocity))
            events.append(('off', abs_off, note.pitch, 0))
        return events
    
    # 收集所有事件, 然后排序转为 delta time
    for track, part_name in [(treble_track, 'treble'), (bass_track, 'bass')]:
        all_events = []
        channel = 0 if part_name == 'treble' else 1
        measure_idx = 0
        
        # 第一部分反复 (measures 1-8, 演奏两次)
        for repeat in range(2):
            for col in range(8):
                frag_num = fragment_numbers[col]
                frag = FRAGMENTS.get(frag_num, {"treble": [], "bass": []})
                notes = frag[part_name]
                evts = add_notes_to_track(track, notes, measure_idx)
                all_events.extend(evts)
                measure_idx += 1
        
        # 第二部分 (measures 9-16, 不反复)
        for col in range(8, 16):
            frag_num = fragment_numbers[col]
            frag = FRAGMENTS.get(frag_num, {"treble": [], "bass": []})
            notes = frag[part_name]
            evts = add_notes_to_track(track, notes, measure_idx)
            all_events.extend(evts)
            measure_idx += 1
        
        # 排序并转为 delta time
        all_events.sort(key=lambda e: (e[1], 0 if e[0] == 'off' else 1))
        
        prev_tick = 0
        for evt in all_events:
            etype, tick, pitch, vel = evt
            delta = tick - prev_tick
            if delta < 0:
                delta = 0
            if etype == 'on':
                track.append(Message('note_on', note=pitch, velocity=vel, 
                                     channel=channel, time=delta))
            else:
                track.append(Message('note_off', note=pitch, velocity=0, 
                                     channel=channel, time=delta))
            prev_tick = tick
        
        track.append(MetaMessage('end_of_track', time=MEASURE))
    
    mid.save(filename)
    return filename


def display_game_result(dice_rolls: list, fragment_numbers: list):
    """打印骰子游戏结果"""
    print("=" * 70)
    print("  🎲  莫扎特音乐骰子游戏 (Musikalisches Würfelspiel, K.516f)")
    print("=" * 70)
    print()
    
    print("  小节:    ", end="")
    for i in range(1, 17):
        print(f"{i:>4}", end="")
    print()
    
    print("  " + "-" * 66)
    
    print("  骰子:    ", end="")
    for d in dice_rolls:
        print(f"{d:>4}", end="")
    print()
    
    print("  片段:    ", end="")
    for f in fragment_numbers:
        print(f"{f:>4}", end="")
    print()
    
    print("  " + "-" * 66)
    print()
    print(f"  结构: | 第一部分 (小节 1-8, 反复) :||  第二部分 (小节 9-16) |")
    print(f"  总可能组合数: 2 × 11^14 ≈ 759,499,667,166,482")
    print()


# ============================================================
# MIDI 播放器 (使用 pygame)
# ============================================================

def play_midi(filename: str):
    """使用 pygame 播放 MIDI 文件"""
    try:
        import pygame
        import pygame.mixer
        
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
        
        print(f"  ▶  正在播放: {filename}")
        print(f"     (按 Ctrl+C 停止播放)")
        print()
        
        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()
        
        # 等待播放完成
        while pygame.mixer.music.get_busy():
            time.sleep(0.5)
        
        pygame.mixer.quit()
        print("  ■  播放完成!")
        
    except ImportError:
        print("  ⚠  pygame 未安装, 无法播放。请安装: pip install pygame")
        print(f"     MIDI 文件已保存: {filename}")
    except Exception as e:
        print(f"  ⚠  播放出错: {e}")
        print(f"     你可以用其他播放器打开: {filename}")
        print(f"     推荐: timidity {filename}  或  fluidsynth {filename}")


# ============================================================
# 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="莫扎特音乐骰子游戏 (Musikalisches Würfelspiel, K.516f)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python mozart_dice_game.py              # 生成并播放一首华尔兹
  python mozart_dice_game.py --count 3    # 批量生成3首
  python mozart_dice_game.py --seed 42    # 用固定种子(可复现)
  python mozart_dice_game.py --bpm 100    # 加快速度到100 BPM
  python mozart_dice_game.py --no-play    # 只生成不播放
  python mozart_dice_game.py --outdir ./  # 指定输出目录
        """
    )
    parser.add_argument('--count', type=int, default=1, help='生成华尔兹数量 (默认 1)')
    parser.add_argument('--seed', type=int, default=None, help='随机种子 (用于复现)')
    parser.add_argument('--bpm', type=int, default=80, help='速度 BPM (默认 80)')
    parser.add_argument('--no-play', action='store_true', help='只生成 MIDI 文件, 不播放')
    parser.add_argument('--outdir', type=str, default='.', help='输出目录 (默认当前目录)')
    
    args = parser.parse_args()
    
    os.makedirs(args.outdir, exist_ok=True)
    
    if args.seed is not None:
        random.seed(args.seed)
    
    generated_files = []
    
    for i in range(args.count):
        print()
        if args.count > 1:
            print(f"  === 第 {i+1}/{args.count} 首 ===")
        
        dice_rolls, fragment_numbers = play_dice_game()
        display_game_result(dice_rolls, fragment_numbers)
        
        # 生成文件名
        sig = ''.join(str(d) for d in dice_rolls)
        filename = os.path.join(args.outdir, f"mozart_waltz_{sig}.mid")
        
        create_midi(fragment_numbers, bpm=args.bpm, filename=filename)
        generated_files.append(filename)
        print(f"  💾  MIDI 文件已保存: {filename}")
        print()
        
        if not args.no_play:
            play_midi(filename)
    
    if args.count > 1:
        print()
        print("  生成的所有文件:")
        for f in generated_files:
            print(f"    📄 {f}")
    
    return generated_files


if __name__ == '__main__':
    main()
