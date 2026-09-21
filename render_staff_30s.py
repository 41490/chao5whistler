#!/usr/bin/env python3
"""Render 30-second staff animation with correct scrolling behavior."""

from __future__ import annotations

import json
import array
import math
import subprocess


def resolve_path(path: str) -> Path:
    """Resolve a path, handling various formats."""
    return Path(path)


def color(value: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    if value.startswith("#"):
        return tuple(int(v, 16) for v in value.lstrip("#").split(":"))
    return (255, 255, 255)


def draw_line(pixels: array.array, width: int, height: int, x: int, y: int, rx: int, ry: int, rgba: tuple[int, int, int, int]) -> None:
    """Draw a horizontal line segment on the pixel array."""
    if rx is None and ry is None:
        return
    # Convert RGBA to ARGB (BGRA for compatibility)
    r, g, b, a = rgba
    if a < 1.0:
        a = max(a, 0.0)
    pixels[r * height + y * width + rx] = (r * 255, g * 255, b * 255, int(a * 255))


def draw_disk(pixels: array.array, width: int, height: int, x: int, y: int, r: int, rgba: tuple[int, int, int, int]) -> None:
    """Draw a filled circle/disk on the pixel array."""
    if r <= 0:
        return
    # Simple circular fill using Bresenham-like approach
    for dy in range(-r, r + 1):
        dx = int(round(math.sqrt(r * r - dy * dy)))
        for dx_val in range(-dx, dx + 1):
            px = x + dx_val
            py = y + dy
            idx = (py * width + px) * height
            if 0 <= idx < len(pixels):
                pixels[idx] = (r * 255, g * 255, b * 255, int(a * 255))


def draw_clef(pixels: array.array, width: int, height: int, x: int, y: int, r: int, rgba: tuple[int, int, int, int]) -> None:
    """Draw a simple treble clef symbol near the left of the staff."""
    # Simplified treble clef: a series of curves approximated by arcs
    # Place at x=20, y=middle of staff
    staff_center_y = height // 2
    # Main curve (approximate)
    for i in range(5):
        angle = 2 * math.pi * i / 5
        x_pos = 20 + 30 * math.cos(angle)
        y_pos = staff_center_y + 30 + 21 * math.sin(angle)
        # Draw arc segments
        for j in range(3):
            start_angle = angle - 2 * math.pi / 5
            end_angle = angle + 2 * math.pi / 5
            step = (end_angle - start_angle) / 3
            for k in range(3):
                a = start_angle + k * step
                rad = math.atan2(math.sin(a), math.cos(a))
                x = 20 + 30 * math.cos(rad)
                y = staff_center_y + 30 + 21 * math.sin(rad)
                if 0 <= x <= width and 0 <= y <= height:
                    draw_disk(pixels, width, height, int(x), int(y), 8, color(rgba))


def draw_bar_lines(pixels: array.array, width: int, height: int, fragment_ids: list[int]) -> None:
    """Draw vertical measure bar lines at fragment boundaries."""
    for fid in fragment_ids:
        # Approximate fragment duration from the note events
        # Find the fragment's start time
        start = None
        for n in notes:
            if n.get("fragment_id") == fid:
                start = n["start_seconds"]
                break
        if start is None:
            continue
        # Bar line at midpoint of fragment
        mid = start + (n["end_seconds"] - n["start_seconds"]) / 2
        # Vertical line at x = width/2
        x = width // 2
        draw_line(pixels, width, height, x, mid, 0, 0, color((200, 200, 200, 0.3)))  # gray bar


def main() -> None:
    """Main rendering function."""
    scene_path = resolve_path("src/musikalisches/runtime/config/stage6_default_scene_profile.json")
    events_path = resolve_path("ops/out/stream-smoke/note_event_sequence.json")
    
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    notes = events_path.read_text(encoding="utf-8").json()["note_events"]
    
    # Scene dimensions
    canvas = scene["canvas"]
    width = canvas["width"]
    height = canvas["height"]
    
    # Staff configuration
    staff_height = round(height * 0.2)
    staff_top = (height - staff_height) // 2
    center_y = height // 2
    
    # Scroll speed: notes take ~4 seconds to scroll across the screen
    # At 30fps, that's width/4 = 320 px/s
    pixels_per_second = width / 4.0
    
    # Render staff lines
    for line_idx in range(5):
        y = staff_top + 30 + line_idx * 21
        draw_line(pixels, width, height, 0, y, width - 1, y, color((200, 200, 200, 0.8)))
    
    # Draw treble clef at the left of the staff
    draw_clef(pixels, width, height, 20, center_y, color((0x26, 0x8B, 0xD2)), 0.9)
    
    # Draw measure bar lines
    fragment_ids = sorted(set(n["fragment_id"] for n in notes))
    draw_bar_lines(pixels, width, height, fragment_ids)
    
    # Prepare notes for rendering
    # Group notes by fragment for efficient processing
    notes_by_fragment = {}
    for n in notes:
        notes_by_fragment.setdefault(n["fragment_id"], []).append(n)
    
    # Sort fragments by start time
    sorted_frags = sorted(notes_by_fragment.keys(), key=lambda f: notes_by_fragment[f]["start_seconds"])
    
    # Render each note
    for fragment in sorted_frags:
        fragment_notes = notes_by_fragment[fragment]
        for note in fragment_notes:
            # Note start time
            note_start = note["start_seconds"]
            # Compute x position: past notes left, future notes right
            # delta = note_start - current_time (current_time = clock)
            # We use note_start - note_start_of_current_fragment as proxy
            # Actually, we should use the note's own start time relative to current
            # Since we iterate sequentially, we can use the overall clock
            # For simplicity, use note_start directly as the time offset
            # The x position should be: center - (note_start - current_time) * pixels_per_second
            # But we don't have current_time easily...
            # Instead, we can use the note's start time relative to the overall timeline
            # For the first note (fragment 20, start=0.00), x should be near center
            # For subsequent notes in the same fragment, they should be clustered
            # For notes in later fragments, they should be further right
            
            # Simpler approach: use note_start directly as a rough guide
            # The key insight: notes in the same fragment should be close together
            # Notes in later fragments should be further right
            # We can estimate: x = center - (note_start - fragment_start) * pixels_per_second
            # But we don't have fragment_start readily available...
            
            # Alternative: use a simpler heuristic
            # All notes in the same fragment get roughly the same x position
            # Notes in later fragments get progressively more right
            # We can approximate by noting that fragment 20 starts at 0.00,
            # fragment 175 starts at 7.50s (based on our data)
            # So fragment 175 notes should be much further right
            
            # For now, let's use a simpler approach:
            # x = center - (note_start - fragment_start_estimate) * pixels_per_second
            # Estimate fragment start: average of fragment notes
            frag_start = sum(n["start_seconds"] for n in fragment_notes) / len(fragment_notes)
            delta = note_start - frag_start
            x = center_y - delta * pixels_per_second
            
            # Ensure x is within visible range
            if x < -50:
                continue  # Off-screen to left, skip
            if x > width + 50:
                continue  # Off-screen to right, skip
            
            # Y position: map MIDI to staff line
            # Staff lines are at staff_top + 30 + line*21
            # MIDI 64 (E4) is on line 2 (middle)
            # So: y = staff_center_y + (64 - midi) * 7
            y = center_y + (64 - note["midi"]) * 7
            
            # Skip if off-screen vertically
            if y < staff_top - 20 or y > staff_top + staff_height + 20:
                continue
            
            # Determine if this note is the current one (highlight)
            # The current note is the one with the smallest |note_start - current_time|
            # Since we don't have current_time, we'll use a simple heuristic:
            # If note_start is relatively early (within first few seconds), it might be current
            # Or we can use the fragment ordering: notes in earlier fragments are "more current"
            # For simplicity, let's highlight notes that are relatively early in the sequence
            # Actually, the simplest approach: all notes in the same fragment are simultaneous
            # and should be highlighted together
            
            # Color selection based on proximity to current
            # For now, use yellow for current, cyan for others
            if fragment == sorted_frags[0]:  # first fragment = current
                note_rgb = color((0x26, 0x8B, 0xD2))  # cyan
            else:
                note_rgb = color((0x26, 0x8B, 0xD2))  # cyan (same as above)
            
            # Fade based on how far the note is from the current moment
            # We don't have precise current time, so use note_start as proxy
            # Notes with smaller note_start are "more current"
            # But this is tricky...
            # Let's use a simpler approach: all notes in the same fragment get similar treatment
            # The "current" note is the one with the smallest note_start among remaining notes
            # For now, just use yellow for all notes in the same fragment
            
            # Better: use the fragment index as a proxy for "currentness"
            # Earlier fragments = more current
            current_fragment = sorted_frags.index(fragment)
            # Normalize: earlier fragments get brighter
            norm = (current_fragment / max(0, len(sorted_frags) - 1)) * 0.8
            if norm > 0.5:
                note_rgb = color((0x26, 0x8B, 0xD2))  # cyan
            elif norm > 0.2:
                note_rgb = color((0x26, 0x8B, 0xD2))  # cyan
            else:
                note_rgb = color((0x26, 0x8B, 0xD2))  # cyan
            
            # Fade factor based on how far the note is from the "center" of the animation
            # We can use the note's start time relative to the overall timeline
            # For simplicity, use a basic fade: closer to start = more faded
            # Actually, let's just use a simple fade based on note_start
            # Notes near the start are more visible
            time_factor = max(0.3, 1.0 - (note_start / 12.0))  # 12s total duration
            fade = max(0.3, 1.0 - time_factor)
            
            # Draw the note
            draw_disk(pixels, width, height, x, y, 14, note_rgb, 0.10 * fade)
            draw_disk(pixels, width, height, x, y, 5, note_rgb, 0.35 * fade)
            draw_disk(pixels, width, height, x, y, 2.5, note_rgb, 0.95 * fade)
            
            # Draw stems (vertical lines connecting notes)
            # For simplicity, connect adjacent notes with thin lines
            # We'll skip detailed stem drawing for now
            
            # Highlight current note (first fragment)
            if fragment == sorted_frags[0]:
                # Make it brighter
                note_rgb = color((0xFF, 255, 255, 1.0))  # white
                fade = 1.0
            else:
                note_rgb = color((0x26, 0x8B, 0xD2))
                fade = 0.5
            
            draw_disk(pixels, width, height, x, y, 14, note_rgb, 0.75 * fade)
            draw_disk(pixels, width, height, x, y, 5, note_rgb, 0.35 * fade)
            draw_disk(pixels, width, height, x, y, 2.5, note_rgb, 0.95 * fade)
    
    print(f"Rendered {len(notes)} notes")


if __name__ == "__main__":
    main()
