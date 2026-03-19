#!/usr/bin/env python3
"""
MIDI 播放与检查工具
==================

提供多种方式播放/查看生成的 MIDI 文件:

1. pygame 播放 (需要声卡)
2. 转为 WAV (需要 fluidsynth + soundfont)
3. 文本可视化 (纯终端钢琴卷帘)

用法:
    python midi_player.py mozart_waltz_xxx.mid              # 尝试播放
    python midi_player.py mozart_waltz_xxx.mid --info        # 显示信息
    python midi_player.py mozart_waltz_xxx.mid --piano-roll  # 终端钢琴卷帘
    python midi_player.py mozart_waltz_xxx.mid --to-wav out.wav  # 转 WAV
"""

import argparse
import sys
import os

import mido


def show_info(filename: str):
    """显示 MIDI 文件详细信息"""
    mid = mido.MidiFile(filename)
    
    print(f"\n📄 文件: {filename}")
    print(f"   格式: Type {mid.type}")
    print(f"   轨道: {len(mid.tracks)}")
    print(f"   TPQN: {mid.ticks_per_beat}")
    print(f"   时长: {mid.length:.1f} 秒")
    print()
    
    for i, track in enumerate(mid.tracks):
        notes_on = [m for m in track if m.type == 'note_on' and m.velocity > 0]
        meta = [m for m in track if isinstance(m, mido.MetaMessage)]
        print(f"   轨道 {i}: {track.name}")
        print(f"     事件总数: {len(track)}")
        print(f"     音符数: {len(notes_on)}")
        
        # 找出拍号和速度
        for m in meta:
            if m.type == 'time_signature':
                print(f"     拍号: {m.numerator}/{m.denominator}")
            elif m.type == 'set_tempo':
                bpm = mido.tempo2bpm(m.tempo)
                print(f"     速度: {bpm:.0f} BPM")
    print()


NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def note_name(midi_note: int) -> str:
    return f"{NOTE_NAMES[midi_note % 12]}{midi_note // 12 - 1}"


def piano_roll(filename: str, width: int = 80):
    """在终端中显示简易钢琴卷帘图"""
    mid = mido.MidiFile(filename)
    
    # 收集所有音符
    all_notes = []
    for track in mid.tracks:
        abs_time = 0
        active = {}
        for msg in track:
            abs_time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                active[msg.note] = abs_time
            elif msg.type in ('note_off', 'note_on') and (msg.type == 'note_off' or msg.velocity == 0):
                if msg.note in active:
                    start = active.pop(msg.note)
                    all_notes.append((start, abs_time, msg.note))
    
    if not all_notes:
        print("  没有找到音符!")
        return
    
    # 确定范围
    min_note = min(n[2] for n in all_notes)
    max_note = max(n[2] for n in all_notes)
    max_time = max(n[1] for n in all_notes)
    
    # 量化到字符网格
    time_scale = (width - 8) / max_time if max_time > 0 else 1
    
    print(f"\n🎹 钢琴卷帘图: {filename}")
    print(f"   音域: {note_name(min_note)} - {note_name(max_note)}")
    print(f"   时长: {mid.length:.1f}s")
    print()
    
    # 从高到低绘制
    for pitch in range(max_note, min_note - 1, -1):
        label = f"{note_name(pitch):>4} |"
        row = [' '] * (width - 8)
        
        for start, end, note in all_notes:
            if note == pitch:
                col_start = int(start * time_scale)
                col_end = int(end * time_scale)
                col_end = max(col_end, col_start + 1)
                for c in range(col_start, min(col_end, len(row))):
                    row[c] = '█'
        
        line = ''.join(row)
        # 只打印有音符的行
        if '█' in line:
            print(f"  {label}{line}|")
    
    print(f"  {'':>5}+{'-' * (width - 8)}+")
    print()


def play_with_pygame(filename: str):
    """用 pygame 播放"""
    try:
        import pygame
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
        
        print(f"\n  ▶  正在播放: {filename}")
        print(f"     按 Ctrl+C 停止")
        
        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()
        
        import time
        while pygame.mixer.music.get_busy():
            time.sleep(0.3)
        
        pygame.mixer.quit()
        print("  ■  播放完成!\n")
        return True
        
    except Exception as e:
        print(f"\n  ⚠  pygame 播放失败: {e}")
        return False


def convert_to_wav(midi_file: str, wav_file: str):
    """尝试用 fluidsynth 转为 WAV"""
    import subprocess
    
    # 尝试查找 soundfont
    soundfonts = [
        '/usr/share/sounds/sf2/FluidR3_GM.sf2',
        '/usr/share/soundfonts/FluidR3_GM.sf2',
        '/usr/share/sounds/sf2/default-GM.sf2',
        '/usr/share/soundfonts/default.sf2',
    ]
    
    sf = None
    for s in soundfonts:
        if os.path.exists(s):
            sf = s
            break
    
    if sf is None:
        print("  ⚠  未找到 SoundFont 文件。")
        print("     请安装: sudo apt install fluid-soundfont-gm")
        print("     或手动指定: fluidsynth -ni <soundfont.sf2> " + midi_file + " -F " + wav_file)
        return False
    
    try:
        result = subprocess.run(
            ['fluidsynth', '-ni', sf, midi_file, '-F', wav_file, '-r', '44100'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"  ✅  WAV 文件已生成: {wav_file}")
            return True
        else:
            print(f"  ⚠  fluidsynth 失败: {result.stderr}")
            return False
    except FileNotFoundError:
        print("  ⚠  fluidsynth 未安装。")
        print("     请安装: sudo apt install fluidsynth fluid-soundfont-gm")
        return False


def main():
    parser = argparse.ArgumentParser(description="MIDI 播放与检查工具")
    parser.add_argument('file', help='MIDI 文件路径')
    parser.add_argument('--info', action='store_true', help='显示文件信息')
    parser.add_argument('--piano-roll', action='store_true', help='显示钢琴卷帘图')
    parser.add_argument('--to-wav', type=str, default=None, help='转换为 WAV 文件')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"错误: 文件不存在 - {args.file}")
        sys.exit(1)
    
    if args.info:
        show_info(args.file)
    elif args.piano_roll:
        piano_roll(args.file)
    elif args.to_wav:
        convert_to_wav(args.file, args.to_wav)
    else:
        show_info(args.file)
        success = play_with_pygame(args.file)
        if not success:
            print("  💡  替代播放方式:")
            print(f"     timidity {args.file}")
            print(f"     fluidsynth /usr/share/sounds/sf2/FluidR3_GM.sf2 {args.file}")
            print(f"     或用任何 MIDI 播放器打开该文件")
            print()
            piano_roll(args.file)


if __name__ == '__main__':
    main()
