package audio

import (
	"math"

	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
)

// MixerV2 is the ambient-engine bus mixer described in #28/#31. Unlike
// the bell-era Mixer (`mixer.go`, frozen), v2 is built around long-lived
// continuous voices (drone + bed) modulated by the slow composer state,
// with a sparse accent bank routed off composer.Accent. There is no
// per-second NoteTrigger queue.
//
// Layer map:
//
//	L0   drone     — DroneVoice, gain ∝ (1 - 0.4*Density), mode -> root Hz
//	L0.5 tonal-bed — TonalBedVoice, sample-based looped bed (#32)
//	L1   bed       — BedVoice (filtered pink noise), gain ∝ Brightness
//	L2   accent    — short Karplus voice from BellBank, fired on composer.Accent
//	all          — shared Reverb send (mixerSpaceWet) for unified space
type MixerV2 struct {
	sampleRate      int
	fps             int
	samplesPerFrame int

	drone     *DroneVoice
	bed       *BedVoice
	tonalBed  *TonalBedVoice

	bells     *BellBank
	accentMax int

	// reverb is the shared "space" — every continuous layer plus the
	// accent bus sends through it at its own wet ratio (#32).
	reverb *Reverb

	pendingAccents []v2PendingAccent
	activeAccents  []v2ActiveAccent

	frameBuf []float32

	// Dial gains so callers can map dB to linear without rebuilding voices.
	droneGain    float32 // base scalar applied on top of voice's own slew
	bedGain      float32
	tonalBedGain float32
	accentGain   float32
	masterGain   float32

	// Wet ratios for the shared reverb send. Continuous layers go in at
	// a low wet so the floor stays defined; accents go in heavy so the
	// space tail is the strongest part of an accent.
	wetContinuous float32
	wetAccent     float32

	// Cached state used by metric reporting.
	lastState composer.State
}

type v2PendingAccent struct {
	accent          composer.Accent
	triggerAtSample int
}

type v2ActiveAccent struct {
	voice  *KarplusVoice
	pan    float32
	gain   float32
	offset int // negative offset: how many samples in we already are
}

// NewMixerV2 constructs the v2 mixer. accentMax caps simultaneously
// active accent voices (default 4 if you pass 0 or negative).
func NewMixerV2(sampleRate, fps, accentMax int) *MixerV2 {
	if accentMax <= 0 {
		accentMax = 4
	}
	return &MixerV2{
		sampleRate:      sampleRate,
		fps:             fps,
		samplesPerFrame: sampleRate / fps,
		drone:           NewDroneVoice(sampleRate),
		bed:             NewBedVoice(sampleRate, 0xb1d),
		tonalBed:        NewTonalBedVoice(sampleRate, nil),
		reverb:          NewReverb(sampleRate),
		accentMax:       accentMax,
		droneGain:    1.0,
		bedGain:      1.0,
		tonalBedGain: 1.0,
		accentGain:   1.0,
		// 0.55 master leaves ~5 dB of headroom for inter-sample peaks
		// after AAC encoding plus the shared-reverb send stacking;
		// empirically keeps true-peak under -1.5 dBTP across the
		// drone+tonal+bed+accent layered mix.
		masterGain:    0.55,
		wetContinuous: 0.06,
		wetAccent:     0.45,
	}
}

// Per-layer gain dials. Values are linear scalars; use GainToLinear to
// convert from dB.
func (m *MixerV2) SetDroneGain(g float32)    { m.droneGain = g }
func (m *MixerV2) SetBedGain(g float32)      { m.bedGain = g }
func (m *MixerV2) SetTonalBedGain(g float32) { m.tonalBedGain = g }
func (m *MixerV2) SetAccentGain(g float32)   { m.accentGain = g }
func (m *MixerV2) SetMasterGain(g float32)   { m.masterGain = g }

// SetAccentBank installs the BellBank used to spawn accent voices.
// Passing nil disables accents (useful for testing pure ambient layers).
func (m *MixerV2) SetAccentBank(b *BellBank) { m.bells = b }

// SetTonalBedPCM installs (or replaces) the tonal bed sample. nil/empty
// disables the layer.
func (m *MixerV2) SetTonalBedPCM(pcm []float32) {
	m.tonalBed = NewTonalBedVoice(m.sampleRate, pcm)
}

// SetWet allows tuning of the shared-space send levels. Continuous layers
// sit low (~0.1) so the floor stays defined; accents go heavier so their
// tails define the perceived "space" of the engine.
func (m *MixerV2) SetWet(continuous, accent float32) {
	m.wetContinuous = clampUnit(continuous)
	m.wetAccent = clampUnit(accent)
}

// ApplyOutput consumes one composer tick: updates the long-lived voices'
// targets from State and queues any Accents to spawn on the next frame.
func (m *MixerV2) ApplyOutput(o composer.Output) {
	m.lastState = o.State
	m.drone.SetMode(o.State.Mode)
	// Density modestly ducks the drone so accents have room. Even at
	// Density=0 the drone sits at ~0.16 — never silent. Targets chosen
	// so drone+bed sum stays under -1.5 dBTP after softClip headroom.
	m.drone.SetTargetGain(0.16 * (1 - 0.4*float32(o.State.Density)))
	// Bed swells with brightness; never below 0.04 so the bed is always
	// audible (a defining property of the ambient engine).
	m.bed.SetTargetGain(0.04 + 0.16*float32(o.State.Brightness))
	// Tonal bed sits between drone and bed. SectionRest dips it so the
	// engine breathes; everywhere else the tonal layer carries the floor.
	tonalTarget := float32(0.18)
	if o.State.Section == composer.SectionRest {
		tonalTarget = 0.10
	}
	m.tonalBed.SetTargetGain(tonalTarget)

	for _, a := range o.Accents {
		// Random small offset within first 100 ms of the second so two
		// accents in the same tick (uncommon but possible) don't stack.
		off := (len(m.pendingAccents) % 4) * (m.sampleRate / 40)
		m.pendingAccents = append(m.pendingAccents, v2PendingAccent{
			accent:          a,
			triggerAtSample: off,
		})
	}
}

// LastState returns the most recent composer State that was fed into the
// mixer. Used by render-audio-v2's sidecar.
func (m *MixerV2) LastState() composer.State { return m.lastState }

// RenderFrame emits one stereo float32 frame. Continuous voices play
// every sample; accents are spawned and decayed on top.
func (m *MixerV2) RenderFrame() []float32 {
	n := m.samplesPerFrame
	if cap(m.frameBuf) < n*2 {
		m.frameBuf = make([]float32, n*2)
	}
	out := m.frameBuf[:n*2]
	clear(out)

	// Spawn any accents whose offset falls inside this frame.
	remaining := m.pendingAccents[:0]
	for _, p := range m.pendingAccents {
		if p.triggerAtSample < n {
			m.spawnAccent(p.accent, -p.triggerAtSample)
		} else {
			p.triggerAtSample -= n
			remaining = append(remaining, p)
		}
	}
	m.pendingAccents = remaining

	for i := 0; i < n; i++ {
		// L0 drone
		drone := m.drone.NextSample() * m.droneGain
		// L0.5 tonal bed (sample-based)
		tonal := m.tonalBed.NextSample() * m.tonalBedGain
		// L1 bed (synth pink noise)
		bed := m.bed.NextSample() * m.bedGain
		mono := drone + tonal + bed

		// Accents (if any) get summed dry first.
		var accentMix float32
		if len(m.activeAccents) > 0 {
			for idx := range m.activeAccents {
				v := &m.activeAccents[idx]
				if v.offset < 0 {
					v.offset++
					continue
				}
				if v.voice == nil || v.voice.Done() {
					continue
				}
				accentMix += v.voice.NextSample() * v.gain
			}
		}
		accentDry := accentMix * m.accentGain

		// Single shared reverb send: continuous layers go in light, the
		// accent bus heavy. The reverb instance is one bus so all layers
		// occupy the same room.
		spaceIn := mono*m.wetContinuous + accentDry*m.wetAccent
		spaceOut := m.reverb.Process(spaceIn)

		// Balanced linear pan on accent dry — total energy <= 1 across L+R
		// so adding drone+bed+tonal (centred) cannot push either channel
		// past unity.
		var panL, panR float32 = 0.5, 0.5
		if len(m.activeAccents) > 0 {
			pan := m.activeAccents[0].pan
			panL = 1.0 - pan
			panR = pan
		}
		l := (mono + accentDry*panL + spaceOut) * m.masterGain
		r := (mono + accentDry*panR + spaceOut) * m.masterGain

		out[i*2] = softClipV2(l)
		out[i*2+1] = softClipV2(r)
	}

	// Reap finished accents.
	alive := m.activeAccents[:0]
	for _, v := range m.activeAccents {
		if v.voice != nil && !v.voice.Done() {
			alive = append(alive, v)
		}
	}
	m.activeAccents = alive

	return out
}

func (m *MixerV2) spawnAccent(a composer.Accent, offset int) {
	if m.bells == nil {
		return
	}
	if len(m.activeAccents) >= m.accentMax {
		// Steal the oldest voice — keeps polyphony bounded.
		m.activeAccents = m.activeAccents[1:]
	}
	pitch := pitchForAccent(a)
	v := m.bells.SynthVoice(pitch, float32(a.Velocity))
	pan := notePan(pitch.Note)
	m.activeAccents = append(m.activeAccents, v2ActiveAccent{
		voice:  v,
		pan:    pan,
		gain:   1.0,
		offset: offset,
	})
}

// pitchForAccent maps a composer.Accent (Mode + Degree + Octave) to a
// concrete pentatonic Pitch. Mode picks the rotation of the pentatonic
// scale; Degree is the 0..4 step within it.
func pitchForAccent(a composer.Accent) Pitch {
	notes := pentatonicForMode(a.FromMode)
	deg := a.Degree
	if deg < 0 {
		deg = 0
	}
	if deg >= len(notes) {
		deg = len(notes) - 1
	}
	octave := OctaveMid
	switch a.Octave {
	case 3:
		octave = OctaveLow
	case 4:
		octave = OctaveMid
	case 5:
		octave = OctaveHigh
	}
	return Pitch{Note: notes[deg], Octave: octave}
}

// pentatonicForMode rotates the 五声 (五音) order to suggest a different
// "tonic feel" per mode without leaving the pentatonic scale family.
func pentatonicForMode(m composer.Mode) []Note {
	base := []Note{NoteGong, NoteShang, NoteJue, NoteZhi, NoteYu}
	var rot int
	switch m {
	case composer.ModeYo:
		rot = 0 // 宫
	case composer.ModeHira:
		rot = 1 // 商
	case composer.ModeIn:
		rot = 2 // 角
	case composer.ModeRyo:
		rot = 4 // 羽
	}
	out := make([]Note, len(base))
	for i := range base {
		out[i] = base[(i+rot)%len(base)]
	}
	return out
}

// softClipV2 — same shape as legacy softClip but exported here so we can
// evolve it independently if the v2 master bus needs different limiting.
func softClipV2(x float32) float32 {
	if x > 1.5 {
		return 1.0
	}
	if x < -1.5 {
		return -1.0
	}
	return float32(math.Tanh(float64(x)))
}

func clampUnit(x float32) float32 {
	if x < 0 {
		return 0
	}
	if x > 1 {
		return 1
	}
	return x
}
