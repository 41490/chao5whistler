# ASCII Dice Animation Layer Example

This demonstrates the output from `render_dice_layer.py` for issue #85.

## Dice Animation Overview

Each dice roll (2-12) is visualized as:
1. **Number Display**: The dice roll value shown prominently
2. **Dissipation Effect**: The number transforms into | - _ / \ characters
3. **Left Drift**: Characters drift left toward the staff area
4. **Progress Counter**: Bottom counter increments with each cycle

## Sample Animation Frames

Frame 0-4 (Dice roll: 2):
```
2 . . . .          Frame 0: Initial number
. 2 . . .          Frame 1: Number begins dissipation  
. . 2 . .          Frame 2: Dissipation continues
. . . 2 .          Frame 3: | - _ / \ characters appear
. . . . 2          Frame 4: Characters drift left

| . . . .          Dissipation frame 0 (left drift)
- . . . .          Dissipation frame 1
_ . . . .          Dissipation frame 2
/ . . . .          Dissipation frame 3
\ . . . .          Dissipation frame 4
```

Frame 5-9 (Dice roll: 3):
```
3 3 . . .          Frame 5: New number appears
. 3 3 . .          Frame 6: Dissipation begins
. . 3 3 .          Frame 7: Dissipation continues
. . . 3 3          Frame 8: | - _ / \ characters appear
3 . . . 3          Frame 9: Characters drift left
```

## Technical Details

- **Resolution**: 1280x720 PPM frames (binary format)
- **Frame Rate**: 30 FPS (from scene profile)
- **Dice Rolls**: 14 rolls from note_event_sequence.json: [2,3,4,5,6,7,8,9,10,11,12,7,6,5]
- **Duration**: Each roll lasts 0.857 seconds (12 seconds total / 14 rolls)
- **Dissipation**: 5 frames per roll showing | - _ / \ sequence
- **Output**: 70 PPM frames (14 rolls × 5 dissipation frames)

## Verification Command

```bash
python3 src/musikalisches/tools/render_dice_layer.py \\
  --scene config/stage6_default_scene_profile.json \\
  --note-events ops/out/stream-smoke/note_event_sequence.json \\
  --output-dir test_dice/ \\
  --cycles 14
```

This produces PPM frames that can be composed with other layers using `compose_layers.py` to create the final visualization.

## Related Files

- `src/musikalisches/tools/render_dice_layer.py` - Main renderer
- `config/stage6_default_scene_profile.json` - Scene configuration
- `ops/out/stream-smoke/note_event_sequence.json` - Input data (dice rolls)
- `src/musikalisches/tools/compose_layers.py` - Layer composition utility