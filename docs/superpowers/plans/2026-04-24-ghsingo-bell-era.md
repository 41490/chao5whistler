# ghsingo bell-era Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "6 ocean samples overlay" white-noise audio pipeline of ghsingo with a tuned-bell (编钟) layer driven by a per-second event clustering algorithm, so that random GitHub events produce harmonically coherent generative music.

**Architecture:** A pure `Clusterer` converts per-second events into scheduled `NoteTrigger`s on a strict 五声 × 3 八度 = 15-pitch grid. A `BellBank` routes each note to either a pre-rendered long-form sample (rank 1 + Release) or an on-the-fly Karplus–Strong synth (rank 2–4). The `Mixer` consumes `NoteTrigger`s (replacing the old 6-voice map), and keeps existing BGM crossfade, ducking, reverb, beat, and soft-clip. Only the Release event retains its ocean sample as a layered "big-moment" texture. Config changes plus a `make prepare-bells` target generate the sample bank via `fluidsynth` + FluidR3 Tubular Bells as a ready-to-ship baseline.

**Tech Stack:** Go 1.22 (existing ghsingo module), `github.com/BurntSushi/toml`, `fluidsynth` + `ffmpeg` CLI (asset pre-render only; runtime is pure Go).

**Spec:** `docs/superpowers/specs/2026-04-24-ghsingo-musicality-design.md`
**Issue:** #27
**Preservation branch:** `ghsingo-noisea` (already pushed, snapshot of current noise-era code)

---

## File Structure

```
src/ghsingo/
├── internal/audio/
│   ├── pitch.go             [NEW]  Note/Octave/Pitch types, 15-pitch freq table, filename helpers
│   ├── pitch_test.go        [NEW]
│   ├── cluster.go           [NEW]  Pure Clusterer.Assign(events) → []NoteTrigger
│   ├── cluster_test.go      [NEW]
│   ├── karplus.go           [NEW]  KarplusVoice one-shot bell synth
│   ├── karplus_test.go      [NEW]
│   ├── bellbank.go          [NEW]  BellBank: 15 samples + synth fallback
│   ├── bellbank_test.go     [NEW]
│   ├── mixer.go             [MOD]  Drop voices map, add note triggers, keep BGM/beat/reverb
│   ├── mixer_test.go        [MOD]
│   ├── beat.go              [UNCHANGED]
│   └── reverb.go            [UNCHANGED]
├── internal/config/
│   ├── config.go            [MOD]  Add Bells + Cluster structs; Voices now only optional Release
│   └── config_test.go       [MOD]
├── cmd/live/main.go         [MOD]  Replace voice loading w/ bell-bank + cluster wiring
├── cmd/render-audio/main.go [MOD]  Same wiring
├── scripts/
│   └── render-bells.sh      [NEW]  fluidsynth pre-render for 15 pitches
├── ghsingo.toml             [MOD]  Remove 5 voices, add [audio.bells] + [audio.cluster]
└── Makefile                 [MOD]  Add prepare-bells target

ops/assets/sounds/bells/sampled/
├── C3.wav D3.wav E3.wav G3.wav A3.wav    [NEW assets]
├── C4.wav D4.wav E4.wav G4.wav A4.wav
└── C5.wav D5.wav E5.wav G5.wav A5.wav
```

---

## Task 1: Pentatonic Pitch Table

**Files:**
- Create: `src/ghsingo/internal/audio/pitch.go`
- Test: `src/ghsingo/internal/audio/pitch_test.go`

- [ ] **Step 1: Write failing test**

```go
// src/ghsingo/internal/audio/pitch_test.go
package audio

import (
	"math"
	"testing"
)

func TestPitchFrequency(t *testing.T) {
	cases := []struct {
		note   Note
		octave Octave
		want   float64
	}{
		{NoteGong, OctaveLow, 130.81},  // C3
		{NoteShang, OctaveLow, 146.83}, // D3
		{NoteJue, OctaveMid, 329.63},   // E4
		{NoteZhi, OctaveMid, 392.00},   // G4
		{NoteYu, OctaveHigh, 880.00},   // A5
		{NoteGong, OctaveHigh, 523.25}, // C5
	}
	for _, c := range cases {
		p := Pitch{Note: c.note, Octave: c.octave}
		got := p.Frequency()
		if math.Abs(got-c.want) > 0.5 {
			t.Errorf("Pitch{%v,%v}.Frequency() = %.2f, want %.2f", c.note, c.octave, got, c.want)
		}
	}
}

func TestPitchFilename(t *testing.T) {
	cases := []struct {
		p    Pitch
		want string
	}{
		{Pitch{NoteGong, OctaveLow}, "C3.wav"},
		{Pitch{NoteYu, OctaveHigh}, "A5.wav"},
		{Pitch{NoteZhi, OctaveMid}, "G4.wav"},
	}
	for _, c := range cases {
		if got := c.p.Filename(); got != c.want {
			t.Errorf("Filename() = %q, want %q", got, c.want)
		}
	}
}

func TestAllPitches(t *testing.T) {
	all := AllPitches()
	if len(all) != 15 {
		t.Fatalf("AllPitches length = %d, want 15", len(all))
	}
	seen := map[string]bool{}
	for _, p := range all {
		if seen[p.Filename()] {
			t.Errorf("duplicate pitch %s", p.Filename())
		}
		seen[p.Filename()] = true
	}
}

func TestNoteChineseName(t *testing.T) {
	if NoteGong.Name() != "宫" || NoteYu.Name() != "羽" {
		t.Error("Chinese note names wrong")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestPitch -v`
Expected: FAIL (types undefined).

- [ ] **Step 3: Implement pitch.go**

```go
// src/ghsingo/internal/audio/pitch.go
package audio

import "fmt"

// Note is a pentatonic 五声 note: 宫商角徵羽.
type Note uint8

const (
	NoteGong  Note = 0 // 宫 (C)
	NoteShang Note = 1 // 商 (D)
	NoteJue   Note = 2 // 角 (E)
	NoteZhi   Note = 3 // 徵 (G)
	NoteYu    Note = 4 // 羽 (A)
)

// NoteCount is the size of the pentatonic scale.
const NoteCount = 5

// Octave selects one of the 3 octave bands (low=3, mid=4, high=5).
type Octave uint8

const (
	OctaveLow  Octave = 0 // "3" (C3~A3)
	OctaveMid  Octave = 1 // "4" (C4~A4)
	OctaveHigh Octave = 2 // "5" (C5~A5)
)

// OctaveCount is the number of octave bands.
const OctaveCount = 3

// Pitch is a (note, octave) pair, one of 15 grid points.
type Pitch struct {
	Note   Note
	Octave Octave
}

// baseFreq is the equal-tempered frequency at octave 3 for each note.
var baseFreq = [NoteCount]float64{
	130.81, // C3 (宫)
	146.83, // D3 (商)
	164.81, // E3 (角)
	196.00, // G3 (徵)
	220.00, // A3 (羽)
}

// Frequency returns the equal-tempered frequency in Hz.
func (p Pitch) Frequency() float64 {
	base := baseFreq[p.Note]
	switch p.Octave {
	case OctaveLow:
		return base
	case OctaveMid:
		return base * 2
	case OctaveHigh:
		return base * 4
	}
	return base
}

// Letter returns the Western pitch-class letter (C, D, E, G, A).
func (n Note) Letter() string {
	return [NoteCount]string{"C", "D", "E", "G", "A"}[n]
}

// Name returns the Chinese 五声 name.
func (n Note) Name() string {
	return [NoteCount]string{"宫", "商", "角", "徵", "羽"}[n]
}

// Number returns the canonical Western octave number (3, 4, or 5).
func (o Octave) Number() int {
	return int(o) + 3
}

// Filename returns the canonical WAV filename for this pitch (e.g. "C4.wav").
func (p Pitch) Filename() string {
	return fmt.Sprintf("%s%d.wav", p.Note.Letter(), p.Octave.Number())
}

// AllPitches returns all 15 pitches in (octave, note) order.
func AllPitches() []Pitch {
	out := make([]Pitch, 0, NoteCount*OctaveCount)
	for o := Octave(0); o < OctaveCount; o++ {
		for n := Note(0); n < NoteCount; n++ {
			out = append(out, Pitch{Note: n, Octave: o})
		}
	}
	return out
}
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestPitch -v && go test ./internal/audio/ -run TestAllPitches -run TestNoteChineseName -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
jj describe -m "feat(ghsingo/audio): add pentatonic 15-pitch table for bell-era layer"
jj new
```

---

## Task 2: ClusterEngine — per-second event → note triggers

**Files:**
- Create: `src/ghsingo/internal/audio/cluster.go`
- Test: `src/ghsingo/internal/audio/cluster_test.go`

The ClusterEngine groups events of one second into `NoteTrigger`s using decision #5 (rank by count) and decisions #2 (pentatonic), #3 (Release = ocean overlay), #6 (15-pitch grid), #7 (sample vs synth routing).

**Note on ms_offset:** the daypack format caps at `MaxEventsPerTick=4` and stores events without sub-second timestamps. We preserve the stored event order and deterministically spread them across the first `SpreadMs` of the second (default 500 ms), dividing by event count.

- [ ] **Step 1: Write failing tests**

```go
// src/ghsingo/internal/audio/cluster_test.go
package audio

import (
	"reflect"
	"testing"
)

func testClusterConfig() ClusterConfig {
	return ClusterConfig{
		KeepTopN:      4,
		EventTypeIDs:  []uint8{0, 1, 2, 3, 4}, // Push, Create, Issues, PR, Fork
		AlwaysFireIDs: []uint8{5},             // ReleaseEvent
		Velocities:    [4]float32{1.00, 0.75, 0.60, 0.45},
		ReleaseVelocity: 1.00,
		OctaveRank1:   OctaveMid,
		OctaveRank2:   []Octave{OctaveMid, OctaveHigh},
		OctaveRank3:   OctaveHigh,
		OctaveRank4:   OctaveLow,
		OctaveRelease: OctaveHigh,
		SpreadMs:      500,
	}
}

func TestClusterAllSameType(t *testing.T) {
	evs := []EventEntry{
		{TypeID: 0}, {TypeID: 0}, {TypeID: 0}, {TypeID: 0},
	}
	triggers := Assign(evs, testClusterConfig())
	if len(triggers) != 4 {
		t.Fatalf("len(triggers) = %d, want 4", len(triggers))
	}
	for i, tr := range triggers {
		if tr.Pitch.Note != NoteGong {
			t.Errorf("trigger %d: note = %v, want NoteGong", i, tr.Pitch.Note)
		}
		if tr.Pitch.Octave != OctaveMid {
			t.Errorf("trigger %d: octave = %v, want OctaveMid (rank 1)", i, tr.Pitch.Octave)
		}
		if tr.Source != SourceSample {
			t.Errorf("trigger %d: source = %v, want SourceSample", i, tr.Source)
		}
		if tr.Velocity != 1.00 {
			t.Errorf("trigger %d: velocity = %v, want 1.00", i, tr.Velocity)
		}
	}
	// ms offsets should be 0, 125, 250, 375 (500/4 step).
	want := []int{0, 125, 250, 375}
	got := []int{triggers[0].MsOffset, triggers[1].MsOffset, triggers[2].MsOffset, triggers[3].MsOffset}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ms offsets = %v, want %v", got, want)
	}
}

func TestClusterRankMapping(t *testing.T) {
	// Push×2, Issues×1, Create×1  → ranks: Push=1, Issues=2, Create=3 (tie broken by TypeID ascending)
	// Actually Issues (id 2) and Create (id 1) tie at 1; the tie-break is stable-by-TypeID ascending.
	evs := []EventEntry{
		{TypeID: 0}, // Push
		{TypeID: 1}, // Create
		{TypeID: 0}, // Push
		{TypeID: 2}, // Issues
	}
	triggers := Assign(evs, testClusterConfig())
	if len(triggers) != 4 {
		t.Fatalf("len(triggers) = %d, want 4", len(triggers))
	}
	// Find the trigger for the Issues event (should be rank 3 = NoteJue, OctaveHigh).
	// Order is preserved from events, so:
	//   evs[0] Push    rank 1 → NoteGong @ OctaveMid
	//   evs[1] Create  rank 2 → NoteShang @ OctaveMid (first rank-2 occurrence)
	//   evs[2] Push    rank 1 → NoteGong @ OctaveMid
	//   evs[3] Issues  rank 3 → NoteJue @ OctaveHigh
	wantNotes := []Note{NoteGong, NoteShang, NoteGong, NoteJue}
	for i, tr := range triggers {
		if tr.Pitch.Note != wantNotes[i] {
			t.Errorf("trigger %d: note = %v, want %v", i, tr.Pitch.Note, wantNotes[i])
		}
	}
	// Rank 1 (Push) sources: SourceSample; ranks 2/3/4 use SourceSynth.
	if triggers[0].Source != SourceSample || triggers[2].Source != SourceSample {
		t.Error("rank-1 triggers should be SourceSample")
	}
	if triggers[1].Source != SourceSynth || triggers[3].Source != SourceSynth {
		t.Error("rank>1 triggers should be SourceSynth")
	}
}

func TestClusterRank2OctaveAlternation(t *testing.T) {
	// Push×1, Issues×3 (rank 2 in this config: Push=1=rank2, Issues=3=rank1)
	// Push appears twice as rank 2? Actually Issues=3 → rank 1, Push=1 → rank 2.
	// Make Issues the main so Push becomes rank 2, and test that *repeated* rank-2
	// events alternate octaves.
	evs := []EventEntry{
		{TypeID: 2}, // Issues
		{TypeID: 0}, // Push (rank 2, 1st occurrence → OctaveMid)
		{TypeID: 2},
		{TypeID: 0}, // Push (rank 2, 2nd occurrence → OctaveHigh)
	}
	triggers := Assign(evs, testClusterConfig())
	// Find the two Push triggers (note=NoteShang is rank-2 → wait, no:
	// rank 1 = Issues (count 2) → NoteGong. rank 2 = Push (count 2, tied—tie-break by TypeID ascending: Push 0 < Issues 2).
	// Hmm, Push and Issues tied. Tie-break: ascending TypeID → Push=rank1.
	// Let me make counts clearly distinct.
	evs2 := []EventEntry{
		{TypeID: 2}, {TypeID: 2}, {TypeID: 2}, // Issues ×3 → rank 1
		{TypeID: 0}, // Push ×1 → rank 2 but only 1 occurrence; need another to test alternation:
	}
	triggers2 := Assign(evs2, testClusterConfig())
	_ = triggers2 // rank-2 with only 1 push → OctaveMid; alternation untested here

	// Construct 5 events (exceeds cap 4 — will be truncated). Use 4 clear rank-2 occurrences:
	evs3 := []EventEntry{
		{TypeID: 2}, // Issues ×2 → rank 1
		{TypeID: 0}, // Push (rank 2 #1 → OctaveMid)
		{TypeID: 2},
		{TypeID: 0}, // Push (rank 2 #2 → OctaveHigh)
	}
	triggers3 := Assign(evs3, testClusterConfig())
	if len(triggers3) != 4 {
		t.Fatalf("len = %d, want 4", len(triggers3))
	}
	// Push events are at index 1 (1st push) and 3 (2nd push)
	if triggers3[1].Pitch.Octave != OctaveMid {
		t.Errorf("Push#1 octave = %v, want OctaveMid", triggers3[1].Pitch.Octave)
	}
	if triggers3[3].Pitch.Octave != OctaveHigh {
		t.Errorf("Push#2 octave = %v, want OctaveHigh", triggers3[3].Pitch.Octave)
	}
}

func TestClusterReleaseAlwaysFires(t *testing.T) {
	evs := []EventEntry{
		{TypeID: 5}, // Release
	}
	triggers := Assign(evs, testClusterConfig())
	if len(triggers) != 1 {
		t.Fatalf("len = %d, want 1", len(triggers))
	}
	tr := triggers[0]
	if tr.Pitch.Note != NoteYu {
		t.Errorf("Release note = %v, want NoteYu", tr.Pitch.Note)
	}
	if tr.Pitch.Octave != OctaveHigh {
		t.Errorf("Release octave = %v, want OctaveHigh", tr.Pitch.Octave)
	}
	if !tr.WithOcean {
		t.Error("Release must carry WithOcean=true")
	}
	if tr.Source != SourceSample {
		t.Errorf("Release source = %v, want SourceSample", tr.Source)
	}
	if tr.Velocity != 1.00 {
		t.Errorf("Release velocity = %v, want 1.00", tr.Velocity)
	}
}

func TestClusterEmptySecond(t *testing.T) {
	triggers := Assign(nil, testClusterConfig())
	if len(triggers) != 0 {
		t.Errorf("empty second should produce 0 triggers, got %d", len(triggers))
	}
}

func TestClusterFiltersUnknownTypes(t *testing.T) {
	evs := []EventEntry{
		{TypeID: 99}, // unknown / not in EventTypeIDs or AlwaysFireIDs
		{TypeID: 0},  // Push — valid
	}
	triggers := Assign(evs, testClusterConfig())
	if len(triggers) != 1 {
		t.Fatalf("len = %d, want 1 (unknown filtered)", len(triggers))
	}
	if triggers[0].TypeID != 0 {
		t.Error("remaining trigger should be Push")
	}
}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestCluster -v`
Expected: FAIL (types not defined).

- [ ] **Step 3: Implement cluster.go**

```go
// src/ghsingo/internal/audio/cluster.go
package audio

import "sort"

// EventEntry is the minimal per-event info needed for clustering.
type EventEntry struct {
	TypeID uint8
	Weight uint8
}

// Source selects between pre-rendered sample playback and runtime synth.
type Source uint8

const (
	SourceSample Source = 0 // long pre-rendered WAV (rank 1 + Release)
	SourceSynth  Source = 1 // Karplus-Strong runtime synth (rank 2-4)
)

// NoteTrigger is a scheduled bell strike derived from a GH event.
type NoteTrigger struct {
	Pitch     Pitch
	Velocity  float32
	MsOffset  int  // 0~SpreadMs within the current second
	Source    Source
	TypeID    uint8 // origin event type, useful for video/log
	WithOcean bool  // true only for ReleaseEvent (adds ocean sample)
}

// ClusterConfig governs the per-second event-to-note mapping.
type ClusterConfig struct {
	KeepTopN        int       // top-N event types by count to keep (typically 4)
	EventTypeIDs    []uint8   // event TypeIDs eligible for ranking
	AlwaysFireIDs   []uint8   // event TypeIDs that always trigger (e.g. Release)
	Velocities      [4]float32 // velocity per rank (rank 1..4)
	ReleaseVelocity float32    // velocity for always-fire events
	OctaveRank1     Octave
	OctaveRank2     []Octave   // cycled across repeated rank-2 events
	OctaveRank3     Octave
	OctaveRank4     Octave
	OctaveRelease   Octave
	SpreadMs        int // total ms window (default 500); triggers spaced evenly
}

// rankNotes maps rank index (0-based → rank 1..4) to the pentatonic note.
var rankNotes = [4]Note{NoteGong, NoteShang, NoteJue, NoteZhi}

// Assign converts a list of one-second events (in original order) into
// scheduled NoteTriggers. Events not in EventTypeIDs or AlwaysFireIDs are
// dropped. Events of ranked types are assigned notes by their type's rank;
// AlwaysFire events always produce NoteYu at OctaveRelease with WithOcean.
func Assign(events []EventEntry, cfg ClusterConfig) []NoteTrigger {
	if len(events) == 0 {
		return nil
	}
	rankable := map[uint8]bool{}
	for _, id := range cfg.EventTypeIDs {
		rankable[id] = true
	}
	always := map[uint8]bool{}
	for _, id := range cfg.AlwaysFireIDs {
		always[id] = true
	}

	// Count rankable events per TypeID.
	counts := map[uint8]int{}
	for _, ev := range events {
		if rankable[ev.TypeID] {
			counts[ev.TypeID]++
		}
	}

	// Produce ordered rank list: descending count; tie-break ascending TypeID.
	type pair struct {
		typeID uint8
		count  int
	}
	sorted := make([]pair, 0, len(counts))
	for id, c := range counts {
		sorted = append(sorted, pair{id, c})
	}
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].count != sorted[j].count {
			return sorted[i].count > sorted[j].count
		}
		return sorted[i].typeID < sorted[j].typeID
	})
	if len(sorted) > cfg.KeepTopN {
		sorted = sorted[:cfg.KeepTopN]
	}
	rankOf := map[uint8]int{}
	for idx, p := range sorted {
		rankOf[p.typeID] = idx // 0..3
	}

	// Count rank-2 occurrences as we walk events (for octave alternation).
	rank2Seen := 0

	// Build triggers in event order.
	triggers := make([]NoteTrigger, 0, len(events))
	for _, ev := range events {
		switch {
		case always[ev.TypeID]:
			triggers = append(triggers, NoteTrigger{
				Pitch:     Pitch{Note: NoteYu, Octave: cfg.OctaveRelease},
				Velocity:  cfg.ReleaseVelocity,
				Source:    SourceSample,
				TypeID:    ev.TypeID,
				WithOcean: true,
			})
		case rankable[ev.TypeID]:
			r, ok := rankOf[ev.TypeID]
			if !ok {
				continue // truncated by KeepTopN
			}
			var octave Octave
			var source Source
			switch r {
			case 0:
				octave = cfg.OctaveRank1
				source = SourceSample
			case 1:
				if len(cfg.OctaveRank2) == 0 {
					octave = OctaveMid
				} else {
					octave = cfg.OctaveRank2[rank2Seen%len(cfg.OctaveRank2)]
				}
				rank2Seen++
				source = SourceSynth
			case 2:
				octave = cfg.OctaveRank3
				source = SourceSynth
			case 3:
				octave = cfg.OctaveRank4
				source = SourceSynth
			}
			triggers = append(triggers, NoteTrigger{
				Pitch:    Pitch{Note: rankNotes[r], Octave: octave},
				Velocity: cfg.Velocities[r],
				Source:   source,
				TypeID:   ev.TypeID,
			})
		}
	}

	// Distribute MsOffset evenly across SpreadMs.
	spread := cfg.SpreadMs
	if spread <= 0 {
		spread = 500
	}
	n := len(triggers)
	if n > 0 {
		step := spread / n
		for i := range triggers {
			triggers[i].MsOffset = i * step
		}
	}
	return triggers
}
```

- [ ] **Step 4: Run tests**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestCluster -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
jj describe -m "feat(ghsingo/audio): add per-second event clusterer → note triggers"
jj new
```

---

## Task 3: Karplus–Strong bell voice

**Files:**
- Create: `src/ghsingo/internal/audio/karplus.go`
- Test: `src/ghsingo/internal/audio/karplus_test.go`

- [ ] **Step 1: Write failing test**

```go
// src/ghsingo/internal/audio/karplus_test.go
package audio

import (
	"math"
	"testing"
)

func TestKarplusProducesSignal(t *testing.T) {
	v := NewKarplusVoice(44100, 440.0, 0.996, 1.0)
	var sumSq float64
	for i := 0; i < 4410; i++ { // 100 ms worth
		s := v.NextSample()
		sumSq += float64(s) * float64(s)
	}
	rms := math.Sqrt(sumSq / 4410)
	if rms < 0.001 {
		t.Errorf("Karplus voice RMS = %v, expected > 0.001 (too quiet)", rms)
	}
	if rms > 1.0 {
		t.Errorf("Karplus voice RMS = %v, exceeds 1.0 (clipping)", rms)
	}
}

func TestKarplusDecays(t *testing.T) {
	v := NewKarplusVoice(44100, 440.0, 0.990, 1.0)
	// RMS of first 100ms vs next 100ms: later should be quieter.
	rms := func(n int) float64 {
		var sq float64
		for i := 0; i < n; i++ {
			s := v.NextSample()
			sq += float64(s) * float64(s)
		}
		return math.Sqrt(sq / float64(n))
	}
	early := rms(4410)
	late := rms(4410)
	if late >= early {
		t.Errorf("decay broken: early RMS %v vs late RMS %v (late should be smaller)", early, late)
	}
}

func TestKarplusDoneAfterLifetime(t *testing.T) {
	v := NewKarplusVoice(44100, 440.0, 0.990, 1.0)
	// Burn 3 seconds of samples (well past typical bell ring-out).
	for i := 0; i < 44100*3; i++ {
		v.NextSample()
	}
	if !v.Done() {
		t.Error("voice should be Done after 3 seconds")
	}
	if v.NextSample() != 0 {
		t.Error("Done voice should return silence")
	}
}

func TestKarplusVelocityScales(t *testing.T) {
	vHi := NewKarplusVoice(44100, 440.0, 0.996, 1.0)
	vLo := NewKarplusVoice(44100, 440.0, 0.996, 0.25)
	peakHi, peakLo := float32(0), float32(0)
	for i := 0; i < 1000; i++ {
		h, l := vHi.NextSample(), vLo.NextSample()
		if abs32(h) > peakHi {
			peakHi = abs32(h)
		}
		if abs32(l) > peakLo {
			peakLo = abs32(l)
		}
	}
	if peakLo >= peakHi {
		t.Errorf("velocity not scaling: hi peak %v vs lo peak %v", peakHi, peakLo)
	}
}

func abs32(x float32) float32 {
	if x < 0 {
		return -x
	}
	return x
}
```

- [ ] **Step 2: Run tests (should fail)**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestKarplus -v`
Expected: FAIL.

- [ ] **Step 3: Implement karplus.go**

```go
// src/ghsingo/internal/audio/karplus.go
package audio

import "math/rand"

// KarplusVoice is a one-shot Karplus–Strong plucked-string voice tuned for
// short bell-like attacks. A fresh voice is allocated per trigger.
type KarplusVoice struct {
	buf       []float32
	pos       int
	decay     float64
	remaining int
	velocity  float32
}

// NewKarplusVoice starts a bell ring at the given frequency. decay should be
// 0.99~0.999 (higher = longer ring). velocity scales the initial excitation.
// Auto-silences after ~2 seconds regardless of decay (safety cap).
func NewKarplusVoice(sampleRate int, freq float64, decay float64, velocity float32) *KarplusVoice {
	n := int(float64(sampleRate) / freq)
	if n < 2 {
		n = 2
	}
	buf := make([]float32, n)
	// White-noise excitation (seeded by stdlib global; determinism not required).
	for i := range buf {
		buf[i] = (rand.Float32()*2 - 1) * velocity
	}
	return &KarplusVoice{
		buf:       buf,
		decay:     decay,
		remaining: sampleRate * 2, // 2s lifetime cap
		velocity:  velocity,
	}
}

// NextSample returns one sample and advances the voice state.
func (v *KarplusVoice) NextSample() float32 {
	if v.remaining <= 0 {
		return 0
	}
	out := v.buf[v.pos]
	next := (v.pos + 1) % len(v.buf)
	// Smoothed feedback (average + decay) → natural bell-like high-freq damping.
	averaged := (v.buf[v.pos] + v.buf[next]) * 0.5
	v.buf[v.pos] = float32(float64(averaged) * v.decay)
	v.pos = next
	v.remaining--
	return out
}

// Done reports whether the voice has stopped producing audio.
func (v *KarplusVoice) Done() bool {
	return v.remaining <= 0
}
```

- [ ] **Step 4: Run tests**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestKarplus -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
jj describe -m "feat(ghsingo/audio): add Karplus-Strong bell voice synth"
jj new
```

---

## Task 4: BellBank — sample loader + synth fallback

**Files:**
- Create: `src/ghsingo/internal/audio/bellbank.go`
- Test: `src/ghsingo/internal/audio/bellbank_test.go`

- [ ] **Step 1: Write failing test**

```go
// src/ghsingo/internal/audio/bellbank_test.go
package audio

import (
	"os"
	"path/filepath"
	"testing"
)

// minimalWAV returns a valid 16-bit PCM mono WAV containing a short sine fragment.
func minimalWAV(t *testing.T) []byte {
	// 44-byte header + 100 samples * 2 bytes = 244 bytes.
	data := make([]byte, 44+200)
	copy(data[0:], []byte("RIFF"))
	data[4] = 0xEC
	data[5] = 0x00
	data[6] = 0x00
	data[7] = 0x00 // chunk size = 236
	copy(data[8:], []byte("WAVE"))
	copy(data[12:], []byte("fmt "))
	data[16] = 16 // fmt chunk size 16
	data[20] = 1  // PCM
	data[22] = 1  // mono
	data[24] = 0x44
	data[25] = 0xAC // 44100
	data[32] = 2    // block align
	data[34] = 16   // bits per sample
	copy(data[36:], []byte("data"))
	data[40] = 200 // data chunk size = 200 bytes
	// 100 samples of tiny sine-ish values (non-zero).
	for i := 0; i < 100; i++ {
		v := int16(1000)
		data[44+i*2] = byte(v)
		data[44+i*2+1] = byte(v >> 8)
	}
	return data
}

func TestBellBankLoadsSamples(t *testing.T) {
	dir := t.TempDir()
	// Write C4.wav only.
	if err := os.WriteFile(filepath.Join(dir, "C4.wav"), minimalWAV(t), 0644); err != nil {
		t.Fatal(err)
	}
	bank := NewBellBank(44100)
	n, err := bank.LoadFromDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Errorf("loaded = %d, want 1", n)
	}
	if !bank.HasSample(Pitch{NoteGong, OctaveMid}) {
		t.Error("C4 should be HasSample true")
	}
	if bank.HasSample(Pitch{NoteYu, OctaveHigh}) {
		t.Error("A5 should be HasSample false (not loaded)")
	}
}

func TestBellBankSampleVoice(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "C4.wav"), minimalWAV(t), 0644); err != nil {
		t.Fatal(err)
	}
	bank := NewBellBank(44100)
	if _, err := bank.LoadFromDir(dir); err != nil {
		t.Fatal(err)
	}

	v := bank.SampleVoice(Pitch{NoteGong, OctaveMid}, 1.0)
	if v == nil {
		t.Fatal("SampleVoice returned nil for loaded pitch")
	}
	// Should produce non-zero samples.
	var nonzero int
	for i := 0; i < 100; i++ {
		if v.NextSample() != 0 {
			nonzero++
		}
	}
	if nonzero == 0 {
		t.Error("SampleVoice produced only silence")
	}

	// For a pitch without a sample, SampleVoice returns nil.
	if bank.SampleVoice(Pitch{NoteYu, OctaveHigh}, 1.0) != nil {
		t.Error("SampleVoice should return nil when no sample loaded")
	}
}

func TestBellBankSynthVoiceAlwaysAvailable(t *testing.T) {
	bank := NewBellBank(44100)
	// Empty bank — synth voices should still work for any pitch.
	v := bank.SynthVoice(Pitch{NoteYu, OctaveHigh}, 1.0)
	if v == nil {
		t.Fatal("SynthVoice returned nil")
	}
	var nonzero int
	for i := 0; i < 100; i++ {
		if v.NextSample() != 0 {
			nonzero++
		}
	}
	if nonzero == 0 {
		t.Error("SynthVoice produced only silence")
	}
}
```

- [ ] **Step 2: Run tests (should fail)**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestBellBank -v`
Expected: FAIL.

- [ ] **Step 3: Implement bellbank.go**

```go
// src/ghsingo/internal/audio/bellbank.go
package audio

import (
	"fmt"
	"os"
	"path/filepath"
)

// BellBank maps each pentatonic Pitch to either a pre-rendered long-form sample
// (preferred for rank-1 and Release events) or an on-demand Karplus-Strong
// synth voice (used for rank 2-4 and as a fallback when a sample is missing).
type BellBank struct {
	sampleRate int
	samples    map[Pitch][]float32
	synthDecay float64
}

// NewBellBank creates an empty bank using the given sample rate for synth.
func NewBellBank(sampleRate int) *BellBank {
	return &BellBank{
		sampleRate: sampleRate,
		samples:    make(map[Pitch][]float32),
		synthDecay: 0.996,
	}
}

// SetSynthDecay configures the Karplus-Strong decay coefficient (0.990~0.999).
func (b *BellBank) SetSynthDecay(decay float64) {
	b.synthDecay = decay
}

// LoadFromDir scans dir for {note}{octave}.wav files matching all 15 pitches
// and loads every one it finds. Missing files are silently skipped (the
// runtime falls back to synth). Returns the number of samples loaded.
func (b *BellBank) LoadFromDir(dir string) (int, error) {
	loaded := 0
	for _, p := range AllPitches() {
		path := filepath.Join(dir, p.Filename())
		if _, err := os.Stat(path); err != nil {
			continue // missing → OK, will fall back to synth
		}
		pcm, err := LoadWavFile(path)
		if err != nil {
			return loaded, fmt.Errorf("load %s: %w", path, err)
		}
		b.samples[p] = pcm
		loaded++
	}
	return loaded, nil
}

// HasSample reports whether a pre-rendered sample exists for pitch p.
func (b *BellBank) HasSample(p Pitch) bool {
	_, ok := b.samples[p]
	return ok
}

// SampleVoice returns a new playback voice for p, or nil if no sample is
// loaded for that pitch.
func (b *BellBank) SampleVoice(p Pitch, velocity float32) *SampleVoice {
	pcm, ok := b.samples[p]
	if !ok {
		return nil
	}
	return &SampleVoice{pcm: pcm, velocity: velocity}
}

// SynthVoice returns a new Karplus-Strong synth voice for p.
func (b *BellBank) SynthVoice(p Pitch, velocity float32) *KarplusVoice {
	return NewKarplusVoice(b.sampleRate, p.Frequency(), b.synthDecay, velocity)
}

// SampleVoice is a one-shot sampled-bell playback instance.
type SampleVoice struct {
	pcm      []float32
	pos      int
	velocity float32
}

// NextSample returns one sample and advances the playhead.
func (s *SampleVoice) NextSample() float32 {
	if s.pos >= len(s.pcm) {
		return 0
	}
	v := s.pcm[s.pos] * s.velocity
	s.pos++
	return v
}

// Done reports whether the sample has finished.
func (s *SampleVoice) Done() bool {
	return s.pos >= len(s.pcm)
}
```

- [ ] **Step 4: Run tests**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestBellBank -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
jj describe -m "feat(ghsingo/audio): add BellBank with sample+synth hybrid routing"
jj new
```

---

## Task 5: Config structs — [audio.bells] and [audio.cluster]

**Files:**
- Modify: `src/ghsingo/internal/config/config.go` (add struct types + parsing)
- Modify: `src/ghsingo/internal/config/config_test.go` (new test for bell/cluster sections)

- [ ] **Step 1: Inspect existing test style**

Run: `cd src/ghsingo && grep -n "TestLoad" internal/config/config_test.go | head -5`

- [ ] **Step 2: Add a failing test**

Append to `src/ghsingo/internal/config/config_test.go`:

```go
func TestLoadBellSection(t *testing.T) {
	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "c.toml")
	if err := os.WriteFile(cfgPath, []byte(`
[meta]
profile = "test"
[archive]
source_dir = "x"
daypack_dir = "y"
target_date = "2026-04-01"
[events]
types = ["PushEvent"]
max_per_second = 4
[events.weights]
PushEvent = 10
[audio]
sample_rate = 44100
channels = 2
[audio.bgm]
wav_path = ""
gain_db = 0
[audio.beat]
gain_db = 0
[audio.bells]
bank_dir = "bells"
sample_gain_db = -2.0
synth_gain_db = -4.0
synth_decay = 0.995
[audio.cluster]
keep_top_n = 4
event_types = ["PushEvent", "CreateEvent"]
always_fire = ["ReleaseEvent"]
velocities = [1.0, 0.75, 0.6, 0.45]
release_velocity = 1.0
octave_rank1 = 4
octave_rank2 = [4, 5]
octave_rank3 = 5
octave_rank4 = 3
octave_release = 5
spread_ms = 500
[video]
width = 1280
height = 720
fps = 15
[video.background]
mode = "solid"
switch_every_secs = 1.0
fade_secs = 0.0
[output]
mode = "local"
[output.local]
path = "/tmp/x"
`), 0644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(cfgPath)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Audio.Bells.BankDir != "bells" {
		t.Errorf("BankDir = %q, want %q", cfg.Audio.Bells.BankDir, "bells")
	}
	if cfg.Audio.Bells.SynthDecay != 0.995 {
		t.Errorf("SynthDecay = %v", cfg.Audio.Bells.SynthDecay)
	}
	if cfg.Audio.Cluster.KeepTopN != 4 {
		t.Errorf("KeepTopN = %d", cfg.Audio.Cluster.KeepTopN)
	}
	if len(cfg.Audio.Cluster.OctaveRank2) != 2 {
		t.Errorf("OctaveRank2 = %v", cfg.Audio.Cluster.OctaveRank2)
	}
	if cfg.Audio.Cluster.Velocities[0] != 1.0 {
		t.Errorf("Velocities[0] = %v", cfg.Audio.Cluster.Velocities[0])
	}
}
```

(Add `"path/filepath"` and `"os"` to imports if not already present.)

- [ ] **Step 3: Run test (should fail)**

Run: `cd src/ghsingo && go test ./internal/config/ -run TestLoadBellSection -v`
Expected: FAIL.

- [ ] **Step 4: Add struct types**

Edit `src/ghsingo/internal/config/config.go`:

Replace the `Audio` struct with:
```go
type Audio struct {
	SampleRate   int              `toml:"sample_rate"`
	Channels     int              `toml:"channels"`
	MasterGainDB float64          `toml:"master_gain_db"`
	BGM          AudioBGM         `toml:"bgm"`
	Beat         AudioBeat        `toml:"beat"`
	Voices       map[string]Voice `toml:"voices"`
	Bells        AudioBells       `toml:"bells"`
	Cluster      AudioCluster     `toml:"cluster"`
}
```

Add after the `Voice` struct:
```go
type AudioBells struct {
	BankDir      string  `toml:"bank_dir"`
	SampleGainDB float64 `toml:"sample_gain_db"`
	SynthGainDB  float64 `toml:"synth_gain_db"`
	SynthDecay   float64 `toml:"synth_decay"`
}

type AudioCluster struct {
	KeepTopN        int        `toml:"keep_top_n"`
	EventTypes      []string   `toml:"event_types"`
	AlwaysFire      []string   `toml:"always_fire"`
	Velocities      [4]float32 `toml:"velocities"`
	ReleaseVelocity float32    `toml:"release_velocity"`
	OctaveRank1     int        `toml:"octave_rank1"`
	OctaveRank2     []int      `toml:"octave_rank2"`
	OctaveRank3     int        `toml:"octave_rank3"`
	OctaveRank4     int        `toml:"octave_rank4"`
	OctaveRelease   int        `toml:"octave_release"`
	SpreadMs        int        `toml:"spread_ms"`
}
```

- [ ] **Step 5: Run test**

Run: `cd src/ghsingo && go test ./internal/config/ -run TestLoadBellSection -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
jj describe -m "feat(ghsingo/config): add audio.bells and audio.cluster sections"
jj new
```

---

## Task 6: Mixer refactor — drop 6-voice map, add note-trigger routing

**Files:**
- Modify: `src/ghsingo/internal/audio/mixer.go`
- Modify: `src/ghsingo/internal/audio/mixer_test.go`

This is the central refactor. We delete `voices map`, `TriggerEvent`, `voicePan`, and the old per-type scheduling; we add a `BellBank` reference, a `ReleaseOcean` layer, and a new `ScheduleNotes([]NoteTrigger)` path. BGM, beat, reverb, softClip, ducking remain untouched.

- [ ] **Step 1: Read existing tests and prune**

Open `src/ghsingo/internal/audio/mixer_test.go` first. Keep any test that only uses: `NewMixer`, `SetBGM`, `SetBeat`, `RenderFrame`, `DecodePCM`, `GainToLinear`, `ApplyFadeOut`, `bgmSample` (via crossfade tests). Delete any test that references `RegisterVoice`, `TriggerEvent`, `voicePan`, or `ScheduleSecond` — those APIs no longer exist after this task. Run `go test ./internal/audio/` afterwards; you should see compile errors only in tests you haven't yet deleted.

- [ ] **Step 2: Write failing test for new mixer API**

Append to `src/ghsingo/internal/audio/mixer_test.go`:

```go
func TestMixerScheduleNotes_Synth(t *testing.T) {
	m := NewMixer(44100, 30)
	bank := NewBellBank(44100)
	m.SetBellBank(bank, 1.0, 1.0) // sample gain, synth gain (both linear)

	triggers := []NoteTrigger{
		{
			Pitch:    Pitch{NoteGong, OctaveMid},
			Velocity: 1.0,
			MsOffset: 0,
			Source:   SourceSynth,
		},
	}
	m.ScheduleNotes(triggers)

	// Render one frame worth of audio (44100/30 ≈ 1470 samples L+R).
	frame := m.RenderFrame(nil)
	if len(frame) != (44100/30)*2 {
		t.Fatalf("frame length = %d, want %d", len(frame), (44100/30)*2)
	}
	var peak float32
	for _, s := range frame {
		if s > peak {
			peak = s
		}
		if -s > peak {
			peak = -s
		}
	}
	if peak == 0 {
		t.Error("synth note produced silence")
	}
}

func TestMixerScheduleNotes_SampleFallsBackToSynth(t *testing.T) {
	m := NewMixer(44100, 30)
	bank := NewBellBank(44100) // no samples loaded
	m.SetBellBank(bank, 1.0, 1.0)

	m.ScheduleNotes([]NoteTrigger{{
		Pitch:    Pitch{NoteYu, OctaveHigh},
		Velocity: 1.0,
		Source:   SourceSample, // requested sample, none loaded → falls back to synth
	}})
	frame := m.RenderFrame(nil)
	var peak float32
	for _, s := range frame {
		if s > peak || -s > peak {
			if -s > s {
				peak = -s
			} else {
				peak = s
			}
		}
	}
	if peak == 0 {
		t.Error("sample→synth fallback produced silence")
	}
}

func TestMixerNotePan(t *testing.T) {
	// NoteGong should be centered. NoteShang should be left-leaning.
	// Assert by comparing L vs R energy over one frame.
	render := func(note Note) (l, r float32) {
		m := NewMixer(44100, 30)
		m.SetBellBank(NewBellBank(44100), 1.0, 1.0)
		m.ScheduleNotes([]NoteTrigger{{
			Pitch:    Pitch{note, OctaveMid},
			Velocity: 1.0,
			Source:   SourceSynth,
		}})
		frame := m.RenderFrame(nil)
		for i := 0; i < len(frame); i += 2 {
			l += abs32(frame[i])
			r += abs32(frame[i+1])
		}
		return
	}
	lG, rG := render(NoteGong)
	lS, rS := render(NoteShang)
	// Gong ≈ centered (|l-r| small), Shang should be L > R.
	if abs32(lG-rG) > 0.1*(lG+rG) {
		t.Errorf("NoteGong should be ~centered; L=%v R=%v", lG, rG)
	}
	if lS <= rS {
		t.Errorf("NoteShang should be L-leaning; L=%v R=%v", lS, rS)
	}
}
```

If `abs32` is not already defined in the test file, add:

```go
// already defined in karplus_test.go; if collision occurs, reuse that.
```

(`abs32` is defined in `karplus_test.go` in Task 3; both test files share the `audio` package so it's available.)

- [ ] **Step 3: Run failing tests**

Run: `cd src/ghsingo && go test ./internal/audio/ -run TestMixerScheduleNotes -v`
Expected: FAIL (method not defined).

- [ ] **Step 4: Replace mixer.go**

Replace `src/ghsingo/internal/audio/mixer.go` (lines 1-428) with:

```go
package audio

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"os"
)

// Mixer mixes a looping BGM track, a synthesized beat, and bell note triggers
// (plus an optional ocean layer for Release events) into stereo interleaved
// float32 PCM, one video-frame at a time.
type Mixer struct {
	sampleRate      int
	fps             int
	samplesPerFrame int

	bgmPCM  []float32
	bgmGain float32
	bgmPos  int

	beat        *BeatGenerator
	eventWindow []int

	reverb *Reverb

	bells          *BellBank
	bellSampleGain float32
	bellSynthGain  float32

	oceanPCM  []float32
	oceanGain float32

	active []activeBell // currently ringing bells (sample or synth)

	oceanActive []int // active ocean-sample playheads (indices into oceanPCM)

	secondPos    int // sample counter within current second
	pendingNotes []pendingNote
	frameBuf     []float32
}

type activeBell struct {
	sample *SampleVoice
	synth  *KarplusVoice
	pan    float32
	gain   float32
	// offset negative means start that many samples into this frame.
	offset int
}

type pendingNote struct {
	trigger         NoteTrigger
	triggerAtSample int
}

// NewMixer creates a Mixer for the given sample rate and frame rate.
func NewMixer(sampleRate, fps int) *Mixer {
	return &Mixer{
		sampleRate:      sampleRate,
		fps:             fps,
		samplesPerFrame: sampleRate / fps,
		reverb:          NewReverb(sampleRate),
		eventWindow:     make([]int, 0, 60),
	}
}

// SetBGM sets the background music track (mono PCM) and its linear gain.
func (m *Mixer) SetBGM(pcm []float32, gain float32) {
	m.bgmPCM = pcm
	m.bgmGain = gain
	m.bgmPos = 0
}

// SetBeat enables the synthesized beat layer with the given linear gain.
func (m *Mixer) SetBeat(gain float32) {
	m.beat = NewBeatGenerator(m.sampleRate, gain)
}

// SetBellBank installs the 15-pitch bell bank and the linear gains for its
// sampled and synthesized sources.
func (m *Mixer) SetBellBank(b *BellBank, sampleGain, synthGain float32) {
	m.bells = b
	m.bellSampleGain = sampleGain
	m.bellSynthGain = synthGain
}

// SetReleaseOcean installs the ocean sample that layers on top of a Release
// event's bell strike. pcm may be nil to disable the layer.
func (m *Mixer) SetReleaseOcean(pcm []float32, gain float32) {
	m.oceanPCM = pcm
	m.oceanGain = gain
}

// ScheduleNotes queues one second's worth of pre-clustered NoteTriggers.
// Call this once per second before rendering frames for that second.
func (m *Mixer) ScheduleNotes(triggers []NoteTrigger) {
	m.secondPos = 0
	m.pendingNotes = m.pendingNotes[:0]
	m.updateBeatDensity(len(triggers))

	for _, tr := range triggers {
		triggerAt := tr.MsOffset * m.sampleRate / 1000
		m.pendingNotes = append(m.pendingNotes, pendingNote{
			trigger:         tr,
			triggerAtSample: triggerAt,
		})
	}
}

// bgmSample returns the next BGM sample with crossfade-at-loop.
func (m *Mixer) bgmSample() float32 {
	loopLen := len(m.bgmPCM)
	pos := m.bgmPos % loopLen
	sample := m.bgmPCM[pos]

	crossfade := m.sampleRate / 20 // 50 ms
	if crossfade > 0 && crossfade < loopLen/2 {
		tail := loopLen - crossfade
		if pos >= tail {
			fadeOut := float32(loopLen-pos) / float32(crossfade)
			fadeIn := 1.0 - fadeOut
			headPos := pos - tail
			sample = sample*fadeOut + m.bgmPCM[headPos]*fadeIn
		}
	}
	m.bgmPos++
	return sample
}

// RenderFrame renders one frame of stereo interleaved PCM float32.
// events is accepted for backwards compatibility but is ignored (clustering
// happens upstream via ScheduleNotes).
func (m *Mixer) RenderFrame(_ []struct{ TypeID, Weight uint8 }) []float32 {
	n := m.samplesPerFrame
	if cap(m.frameBuf) < n*2 {
		m.frameBuf = make([]float32, n*2)
	}
	out := m.frameBuf[:n*2]
	clear(out)

	// 1. BGM (mono → stereo).
	if len(m.bgmPCM) > 0 {
		activeCount := float32(len(m.active))
		duckFactor := float32(1.0) - clamp01(activeCount/4.0)*0.5
		eff := m.bgmGain * duckFactor
		for i := 0; i < n; i++ {
			s := m.bgmSample() * eff
			out[i*2] += s
			out[i*2+1] += s
		}
	}

	// 2. Beat (center).
	if m.beat != nil {
		for i := 0; i < n; i++ {
			s := m.beat.NextSample()
			out[i*2] += s
			out[i*2+1] += s
		}
	}

	// 3. Fire pending notes whose triggerAtSample falls within this frame.
	frameEnd := m.secondPos + n
	remaining := m.pendingNotes[:0]
	for _, pn := range m.pendingNotes {
		if pn.triggerAtSample < frameEnd {
			frameOff := pn.triggerAtSample - m.secondPos
			if frameOff < 0 {
				frameOff = 0
			}
			m.spawnBell(pn.trigger, -frameOff)
			if pn.trigger.WithOcean && m.oceanPCM != nil {
				m.oceanActive = append(m.oceanActive, -frameOff)
			}
		} else {
			remaining = append(remaining, pn)
		}
	}
	m.pendingNotes = remaining

	// 4. Active bells.
	for idx := range m.active {
		v := &m.active[idx]
		gainL := v.gain * (1.0 - v.pan)
		gainR := v.gain * v.pan
		for i := 0; i < n; i++ {
			pcmIdx := v.offset + i
			if pcmIdx < 0 {
				continue
			}
			var s float32
			switch {
			case v.sample != nil:
				s = v.sample.NextSample()
			case v.synth != nil:
				s = v.synth.NextSample()
			}
			wet := m.reverb.Process(s)
			out[i*2] += wet * gainL
			out[i*2+1] += wet * gainR
		}
		v.offset += n
	}

	// 5. Active ocean layers (mono, centered).
	if len(m.oceanActive) > 0 && m.oceanPCM != nil {
		keep := m.oceanActive[:0]
		for _, off := range m.oceanActive {
			for i := 0; i < n; i++ {
				pcmIdx := off + i
				if pcmIdx < 0 {
					continue
				}
				if pcmIdx >= len(m.oceanPCM) {
					break
				}
				s := m.oceanPCM[pcmIdx] * m.oceanGain
				out[i*2] += s
				out[i*2+1] += s
			}
			newOff := off + n
			if newOff < len(m.oceanPCM) {
				keep = append(keep, newOff)
			}
		}
		m.oceanActive = keep
	}

	// 6. Advance per-second position.
	m.secondPos += n

	// 7. Drop finished bells.
	alive := m.active[:0]
	for _, v := range m.active {
		done := true
		if v.sample != nil {
			done = v.sample.Done()
		} else if v.synth != nil {
			done = v.synth.Done()
		}
		if !done {
			alive = append(alive, v)
		}
	}
	m.active = alive

	// 8. Soft clip.
	for i := range out {
		out[i] = softClip(out[i])
	}
	return out
}

func (m *Mixer) spawnBell(tr NoteTrigger, offset int) {
	if m.bells == nil {
		return
	}
	pan := notePan(tr.Pitch.Note)
	var v activeBell
	if tr.Source == SourceSample {
		if sv := m.bells.SampleVoice(tr.Pitch, tr.Velocity); sv != nil {
			v = activeBell{sample: sv, pan: pan, gain: m.bellSampleGain, offset: offset}
			m.active = append(m.active, v)
			return
		}
	}
	// Either requested synth, or sample requested but not loaded → synth.
	syn := m.bells.SynthVoice(tr.Pitch, tr.Velocity)
	v = activeBell{synth: syn, pan: pan, gain: m.bellSynthGain, offset: offset}
	m.active = append(m.active, v)
}

// notePan maps a 五声 note to stereo pan position (0=L, 0.5=C, 1=R).
func notePan(n Note) float32 {
	// 宫 centre, 商 偏左, 角 偏右, 徵 远左, 羽 远右.
	pans := [NoteCount]float32{0.50, 0.35, 0.65, 0.25, 0.75}
	return pans[n]
}

func (m *Mixer) updateBeatDensity(eventsThisSecond int) {
	if m.beat == nil {
		return
	}
	if len(m.eventWindow) == cap(m.eventWindow) {
		copy(m.eventWindow, m.eventWindow[1:])
		m.eventWindow = m.eventWindow[:len(m.eventWindow)-1]
	}
	m.eventWindow = append(m.eventWindow, eventsThisSecond)
	total := 0
	for _, c := range m.eventWindow {
		total += c
	}
	m.beat.SetDensity(total)
}

func softClip(x float32) float32 {
	if x > 1.5 {
		return 1.0
	}
	if x < -1.5 {
		return -1.0
	}
	return float32(math.Tanh(float64(x)))
}

func clamp01(x float32) float32 {
	if x < 0 {
		return 0
	}
	if x > 1 {
		return 1
	}
	return x
}

// ---------------------------------------------------------------------------
// WAV decoding (unchanged from noise-era)
// ---------------------------------------------------------------------------

func DecodePCM(data []byte) ([]float32, error) {
	if len(data) < 44 {
		return nil, errors.New("audio: data too short for WAV header")
	}
	if string(data[0:4]) != "RIFF" {
		return nil, errors.New("audio: missing RIFF tag")
	}
	if string(data[8:12]) != "WAVE" {
		return nil, errors.New("audio: missing WAVE tag")
	}

	var (
		audioFormat   uint16
		numChannels   uint16
		bitsPerSample uint16
		dataBytes     []byte
	)
	pos := 12
	for pos+8 <= len(data) {
		chunkID := string(data[pos : pos+4])
		chunkSize := int(binary.LittleEndian.Uint32(data[pos+4 : pos+8]))
		pos += 8

		switch chunkID {
		case "fmt ":
			if chunkSize < 16 || pos+16 > len(data) {
				return nil, errors.New("audio: fmt chunk too small")
			}
			audioFormat = binary.LittleEndian.Uint16(data[pos : pos+2])
			numChannels = binary.LittleEndian.Uint16(data[pos+2 : pos+4])
			bitsPerSample = binary.LittleEndian.Uint16(data[pos+14 : pos+16])
		case "data":
			end := pos + chunkSize
			if end > len(data) {
				end = len(data)
			}
			dataBytes = data[pos:end]
		}

		pos += chunkSize
		if chunkSize%2 != 0 {
			pos++
		}
	}

	if audioFormat != 1 {
		return nil, fmt.Errorf("audio: unsupported format %d (only PCM=1)", audioFormat)
	}
	if bitsPerSample != 16 {
		return nil, fmt.Errorf("audio: unsupported bits per sample %d (only 16)", bitsPerSample)
	}
	if dataBytes == nil {
		return nil, errors.New("audio: no data chunk found")
	}
	_ = numChannels

	numSamples := len(dataBytes) / 2
	out := make([]float32, numSamples)
	for i := 0; i < numSamples; i++ {
		s := int16(binary.LittleEndian.Uint16(dataBytes[i*2 : i*2+2]))
		out[i] = float32(s) / float32(math.MaxInt16)
	}
	return out, nil
}

func LoadWavFile(path string) ([]float32, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("audio: %w", err)
	}
	return DecodePCM(data)
}

func GainToLinear(db float64) float32 {
	return float32(math.Pow(10, db/20.0))
}

func ApplyFadeOut(pcm []float32, tailRatio float32) []float32 {
	n := len(pcm)
	if n == 0 || tailRatio <= 0 {
		return pcm
	}
	fadeStart := int(float32(n) * (1.0 - tailRatio))
	fadeLen := n - fadeStart
	if fadeLen <= 0 {
		return pcm
	}
	out := make([]float32, n)
	copy(out, pcm)
	for i := fadeStart; i < n; i++ {
		t := float32(i-fadeStart) / float32(fadeLen)
		out[i] *= (1.0 - t)
	}
	return out
}
```

- [ ] **Step 5: Run audio package tests**

Run: `cd src/ghsingo && go test ./internal/audio/ -v`
Expected: ALL PASS (new mixer tests + existing DecodePCM/GainToLinear/ApplyFadeOut tests).

- [ ] **Step 6: Commit**

```bash
jj describe -m "feat(ghsingo/audio): refactor Mixer to note-trigger pipeline (drop 6-voice map)"
jj new
```

---

## Task 7: Wire cluster + bellbank into cmd/live

**Files:**
- Modify: `src/ghsingo/cmd/live/main.go`

- [ ] **Step 1: Replace voice loading with bell-bank + cluster**

In `src/ghsingo/cmd/live/main.go`, locate lines 52-81 (the block that does `audio.NewMixer`, `SetBGM`, `SetBeat`, and the `for name, voice := range cfg.Audio.Voices` loop). Replace that block with:

```go
	// --- 3. Create audio mixer: BGM + beat + bell bank + Release ocean ---
	mixer := audio.NewMixer(cfg.Audio.SampleRate, cfg.Video.FPS)

	if cfg.Audio.BGM.WavPath != "" {
		bgmPCM, err := audio.LoadWavFile(cfg.Audio.BGM.WavPath)
		if err != nil {
			slog.Error("load bgm", "err", err)
			os.Exit(1)
		}
		mixer.SetBGM(bgmPCM, audio.GainToLinear(cfg.Audio.BGM.GainDB))
		slog.Info("bgm loaded", "path", cfg.Audio.BGM.WavPath, "samples", len(bgmPCM))
	}

	mixer.SetBeat(audio.GainToLinear(cfg.Audio.Beat.GainDB))
	slog.Info("beat enabled", "gain_db", cfg.Audio.Beat.GainDB)

	bank := audio.NewBellBank(cfg.Audio.SampleRate)
	if cfg.Audio.Bells.SynthDecay > 0 {
		bank.SetSynthDecay(cfg.Audio.Bells.SynthDecay)
	}
	if cfg.Audio.Bells.BankDir != "" {
		loaded, err := bank.LoadFromDir(cfg.Audio.Bells.BankDir)
		if err != nil {
			slog.Error("load bell bank", "err", err)
			os.Exit(1)
		}
		slog.Info("bell bank loaded", "dir", cfg.Audio.Bells.BankDir, "samples", loaded)
	}
	mixer.SetBellBank(bank,
		audio.GainToLinear(cfg.Audio.Bells.SampleGainDB),
		audio.GainToLinear(cfg.Audio.Bells.SynthGainDB),
	)

	// Optional: load ReleaseEvent ocean sample for big-moment layering.
	if rel, ok := cfg.Audio.Voices["ReleaseEvent"]; ok && rel.WavPath != "" {
		pcm, err := audio.LoadWavFile(rel.WavPath)
		if err != nil {
			slog.Warn("load release ocean", "err", err)
		} else {
			mixer.SetReleaseOcean(pcm, audio.GainToLinear(rel.GainDB))
			slog.Info("release ocean loaded", "samples", len(pcm))
		}
	}

	clusterCfg := buildClusterConfig(cfg.Audio.Cluster)
```

- [ ] **Step 2: Add cluster builder helper**

Append to the end of `src/ghsingo/cmd/live/main.go`:

```go
// buildClusterConfig converts config.AudioCluster into audio.ClusterConfig,
// resolving event-type names to uint8 IDs via config.EventTypeID.
func buildClusterConfig(c config.AudioCluster) audio.ClusterConfig {
	resolve := func(names []string) []uint8 {
		out := make([]uint8, 0, len(names))
		for _, n := range names {
			if id, ok := config.EventTypeID[n]; ok {
				out = append(out, id)
			}
		}
		return out
	}
	toOctave := func(n int) audio.Octave {
		switch n {
		case 3:
			return audio.OctaveLow
		case 4:
			return audio.OctaveMid
		case 5:
			return audio.OctaveHigh
		}
		return audio.OctaveMid
	}
	octaveList := func(ns []int) []audio.Octave {
		out := make([]audio.Octave, len(ns))
		for i, n := range ns {
			out[i] = toOctave(n)
		}
		return out
	}
	return audio.ClusterConfig{
		KeepTopN:        c.KeepTopN,
		EventTypeIDs:    resolve(c.EventTypes),
		AlwaysFireIDs:   resolve(c.AlwaysFire),
		Velocities:      c.Velocities,
		ReleaseVelocity: c.ReleaseVelocity,
		OctaveRank1:     toOctave(c.OctaveRank1),
		OctaveRank2:     octaveList(c.OctaveRank2),
		OctaveRank3:     toOctave(c.OctaveRank3),
		OctaveRank4:     toOctave(c.OctaveRank4),
		OctaveRelease:   toOctave(c.OctaveRelease),
		SpreadMs:        c.SpreadMs,
	}
}
```

- [ ] **Step 3: Replace ScheduleSecond call**

Find the block (old lines 205-213):
```go
				if currentTick.Second != lastSecond {
					evs := make([]struct{ TypeID, Weight uint8 }, len(currentTick.Events))
					for i, ev := range currentTick.Events {
						evs[i].TypeID = ev.TypeID
						evs[i].Weight = ev.Weight
					}
					mixer.ScheduleSecond(evs)
					lastSecond = currentTick.Second
				}
```

Replace with:
```go
				if currentTick.Second != lastSecond {
					entries := make([]audio.EventEntry, len(currentTick.Events))
					for i, ev := range currentTick.Events {
						entries[i] = audio.EventEntry{TypeID: ev.TypeID, Weight: ev.Weight}
					}
					triggers := audio.Assign(entries, clusterCfg)
					mixer.ScheduleNotes(triggers)
					lastSecond = currentTick.Second
				}
```

- [ ] **Step 4: Build**

Run: `cd src/ghsingo && go build ./cmd/live`
Expected: success.

- [ ] **Step 5: Commit**

```bash
jj describe -m "feat(ghsingo/live): route events through Clusterer to BellBank"
jj new
```

---

## Task 8: Wire cluster + bellbank into cmd/render-audio

**Files:**
- Modify: `src/ghsingo/cmd/render-audio/main.go`

- [ ] **Step 1: Apply identical wiring**

In `src/ghsingo/cmd/render-audio/main.go`, find the block at lines 68-95 (mixer setup with BGM/Beat/RegisterVoice loop). Replace with the same mixer-setup block from Task 7 Step 1 (BGM, beat, bell bank, release ocean, clusterCfg).

Then find lines 147-155 (the `currentTick.Second != lastSecond` block) and replace the inner content with the Task 7 Step 3 version (build `entries`, call `audio.Assign`, then `mixer.ScheduleNotes`).

Finally, append the `buildClusterConfig` helper at file end (same as Task 7 Step 2 — copy verbatim; both `cmd/` packages are independent `main` packages so duplication is necessary).

- [ ] **Step 2: Build**

Run: `cd src/ghsingo && go build ./cmd/render-audio`
Expected: success.

- [ ] **Step 3: Commit**

```bash
jj describe -m "feat(ghsingo/render-audio): route events through Clusterer to BellBank"
jj new
```

---

## Task 9: render-bells.sh — fluidsynth pre-render script

**Files:**
- Create: `src/ghsingo/scripts/render-bells.sh` (shell script, no test)

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# render-bells.sh — pre-render the 15-pitch pentatonic bell bank for ghsingo
# using fluidsynth + FluidR3_GM.sf2 Tubular Bells (Program 14). Each pitch
# is output as 44100 Hz mono 16-bit PCM.
#
# Requirements: fluidsynth, ffmpeg, FluidR3_GM.sf2 at /usr/share/sounds/sf2/
#
# Output: ../../../ops/assets/sounds/bells/sampled/{note}{octave}.wav
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHSINGO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$(cd "$GHSINGO_DIR/../.." && pwd)/ops/assets/sounds/bells/sampled"
SOUNDFONT="/usr/share/sounds/sf2/FluidR3_GM.sf2"

if ! command -v fluidsynth >/dev/null; then
	echo "error: fluidsynth not installed. Try: apt install fluidsynth" >&2
	exit 1
fi
if ! command -v ffmpeg >/dev/null; then
	echo "error: ffmpeg not installed. Try: apt install ffmpeg" >&2
	exit 1
fi
if [[ ! -f "$SOUNDFONT" ]]; then
	echo "error: soundfont not found at $SOUNDFONT" >&2
	exit 1
fi

mkdir -p "$OUT_DIR"

# Pentatonic pitches → MIDI note numbers.
# C3=48 D3=50 E3=52 G3=55 A3=57 C4=60 D4=62 E4=64 G4=67 A4=69 C5=72 D5=74 E5=76 G5=79 A5=81
declare -a PITCHES=(
	"C3:48" "D3:50" "E3:52" "G3:55" "A3:57"
	"C4:60" "D4:62" "E4:64" "G4:67" "A4:69"
	"C5:72" "D5:74" "E5:76" "G5:79" "A5:81"
)

for entry in "${PITCHES[@]}"; do
	name="${entry%:*}"
	midi="${entry#*:}"
	raw="$(mktemp --suffix=.wav)"
	out="$OUT_DIR/${name}.wav"

	# Tiny MIDI: Program Change 14 (Tubular Bells) on channel 0,
	# note on+off for 3 seconds, then 0.5s of silence for ring-out.
	midifile="$(mktemp --suffix=.mid)"
	python3 - "$midifile" "$midi" <<'PY'
import struct, sys
path, note = sys.argv[1], int(sys.argv[2])
def varlen(n):
    out = bytearray()
    out.append(n & 0x7F)
    while n > 0x7F:
        n >>= 7
        out.insert(0, 0x80 | (n & 0x7F))
    return bytes(out)
# Header: MThd len=6, format 0, 1 track, ticks_per_quarter=480
hdr = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
# Track:
# tempo 500000 us/qn (120bpm)
# program change ch=0 prog=14 (Tubular Bells, 0-indexed)
# note on (delta 0): note vel 100
# note off (delta = 3 * 480 = 1440 ticks = 3 quarter notes = 1.5s? at 120bpm that's 1.5s per quarter? actually 1q=0.5s so 3q=1.5s)
# To get 3 seconds: at 120bpm one beat=0.5s. 3s = 6 beats = 6*480 = 2880 ticks. Plus ring-out 1s = 2 beats = 960 ticks after note-off.
events = bytearray()
events += b"\x00\xFF\x51\x03\x07\xA1\x20"  # tempo 500000
events += b"\x00\xC0\x0E"                   # program change to 14
events += bytes([0x00, 0x90, note, 100])    # note on
events += varlen(2880) + bytes([0x80, note, 0])  # note off after 3s
events += varlen(960) + b"\xFF\x2F\x00"     # end of track after 1s
trk = b"MTrk" + struct.pack(">I", len(events)) + bytes(events)
with open(path, "wb") as f:
    f.write(hdr + trk)
PY

	fluidsynth -ni -g 0.7 -r 44100 -F "$raw" "$SOUNDFONT" "$midifile"
	ffmpeg -y -i "$raw" -ar 44100 -ac 1 -sample_fmt s16 \
		-af "loudnorm=I=-16:LRA=7:TP=-1.5" "$out" 2>/dev/null
	rm -f "$raw" "$midifile"
	echo "rendered $name.wav"
done

echo ""
echo "Bell bank ready at $OUT_DIR"
ls -1 "$OUT_DIR"
```

Save and `chmod +x src/ghsingo/scripts/render-bells.sh`.

- [ ] **Step 2: Verify shell syntax**

Run: `bash -n src/ghsingo/scripts/render-bells.sh`
Expected: no output (syntax OK).

- [ ] **Step 3: Commit**

```bash
chmod +x src/ghsingo/scripts/render-bells.sh
jj describe -m "feat(ghsingo/scripts): add render-bells.sh for fluidsynth bell bank pre-render"
jj new
```

---

## Task 10: Makefile — prepare-bells target

**Files:**
- Modify: `src/ghsingo/Makefile`

- [ ] **Step 1: Insert new target**

In `src/ghsingo/Makefile`, after the line beginning `prepare-assets: normalize-voices` and its body (ends around line 66 with the cosmos ffmpeg call), add:

```makefile
# prepare-bells: render the 15-pitch pentatonic bell sample bank via fluidsynth.
# Requires fluidsynth + ffmpeg + FluidR3_GM.sf2 at /usr/share/sounds/sf2/.
prepare-bells:
	bash scripts/render-bells.sh
```

Also update the `.PHONY` list (lines 7-12) to include `prepare-bells`:

Replace:
```
.PHONY: build build-prepare build-live build-render-audio build-movpixer \
        build-movpixer-linux-amd64 build-movpixer-darwin-arm64 prepare-assets \
        normalize-voices \
        run-prepare run-live run-live-5m render-audio-5m run-movpixer \
        install-units enable start stop status logs \
        fmt vet test clean
```

with:
```
.PHONY: build build-prepare build-live build-render-audio build-movpixer \
        build-movpixer-linux-amd64 build-movpixer-darwin-arm64 prepare-assets \
        prepare-bells normalize-voices \
        run-prepare run-live run-live-5m render-audio-5m run-movpixer \
        install-units enable start stop status logs \
        fmt vet test clean
```

- [ ] **Step 2: Verify target listed**

Run: `cd src/ghsingo && make -n prepare-bells`
Expected: echoes `bash scripts/render-bells.sh` (without executing it).

- [ ] **Step 3: Commit**

```bash
jj describe -m "build(ghsingo): add prepare-bells target to Makefile"
jj new
```

---

## Task 11: Update ghsingo.toml — remove 5 voices, add bells + cluster

**Files:**
- Modify: `src/ghsingo/ghsingo.toml`

- [ ] **Step 1: Replace audio section**

In `src/ghsingo/ghsingo.toml`, delete the five blocks from `[audio.voices.PushEvent]` through `[audio.voices.ForkEvent]` (lines 45-68 in the noise-era config; keep `[audio.voices.ReleaseEvent]` at lines 70-73 intact).

Change `[audio.beat]` `gain_db` from the current value to `-26.0`.

Insert a new block after `[audio.beat]` and before `[audio.voices.ReleaseEvent]`:

```toml
# Bell bank: 15 pentatonic pitches (5 note names × 3 octaves).
# Long samples (rank 1 + Release) + Karplus–Strong synth (rank 2-4 fallback).
[audio.bells]
bank_dir = "../../ops/assets/sounds/bells/sampled"
sample_gain_db = -2.0
synth_gain_db  = -4.0
synth_decay    = 0.996

# Per-second event cluster algorithm.
[audio.cluster]
keep_top_n = 4
event_types = ["PushEvent", "CreateEvent", "IssuesEvent", "PullRequestEvent", "ForkEvent"]
always_fire = ["ReleaseEvent"]
velocities = [1.00, 0.75, 0.60, 0.45]
release_velocity = 1.00
octave_rank1    = 4
octave_rank2    = [4, 5]
octave_rank3    = 5
octave_rank4    = 3
octave_release  = 5
spread_ms       = 500
```

- [ ] **Step 2: Verify config loads**

Run: `cd src/ghsingo && go run ./cmd/render-audio --config ghsingo.toml --duration 1s -o /tmp/ghsingo-smoke.m4a 2>&1 | head -30`

Expected: process starts without config errors. It may fail on missing bell WAVs (that's fine — next tasks generate them). What we're checking here is that the TOML parses cleanly.

If the run errors due to "no daypack", pre-run `prepare` first or skip this step — TOML parsing errors would appear before daypack lookup.

- [ ] **Step 3: Commit**

```bash
jj describe -m "config(ghsingo): replace 5 voices with [audio.bells]+[audio.cluster]"
jj new
```

---

## Task 12: Generate the 15-pitch bell bank

**Files:**
- Create (not by hand — via script): `ops/assets/sounds/bells/sampled/{C3..A5}.wav`

- [ ] **Step 1: Verify fluidsynth installed**

Run: `command -v fluidsynth && ls /usr/share/sounds/sf2/FluidR3_GM.sf2`
Expected: both present.

If `fluidsynth` is not installed:
```bash
sudo apt install -y fluidsynth
```

- [ ] **Step 2: Run prepare-bells**

Run: `cd src/ghsingo && make prepare-bells`
Expected: 15 WAV files rendered; final output lists all 15 files at `ops/assets/sounds/bells/sampled/`.

- [ ] **Step 3: Spot-check one WAV**

Run: `file ops/assets/sounds/bells/sampled/C4.wav && ffprobe -v error -show_entries stream=sample_rate,channels,bits_per_sample,duration ops/assets/sounds/bells/sampled/C4.wav`
Expected: 44100 Hz, 1 channel, 16-bit, ~4s duration.

Optional sanity listen: `ffplay -autoexit -nodisp ops/assets/sounds/bells/sampled/C4.wav`

- [ ] **Step 4: Commit the generated assets**

```bash
jj describe -m "assets(ghsingo): add 15 pre-rendered bell WAVs (Tubular Bells soundfont)"
jj new
```

(The 15 WAVs total ~2-4 MB; committing avoids requiring fluidsynth on every build machine.)

---

## Task 13: 5-minute MP3 validation

**Files:**
- (No source changes; runs existing tool.)

- [ ] **Step 1: Ensure a daypack exists**

Run: `ls ../../var/ghsingo/daypack/*/day.bin 2>/dev/null || cd src/ghsingo && make run-prepare`
Expected: at least one daypack present.

- [ ] **Step 2: Render 5 minutes of audio**

Run: `cd src/ghsingo && make render-audio-5m`
Expected: outputs `/tmp/ghsingo-audio-5m.m4a`.

- [ ] **Step 3: Human listen**

Run: `ffplay -autoexit /tmp/ghsingo-audio-5m.m4a` (or copy off the machine and play locally).
Acceptance criteria:
- Bell strikes clearly audible and pentatonic (no dissonant intervals)
- Release moments are noticeable (bell + ocean layer)
- BGM present but not dominant
- No hard clipping / harsh distortion
- Density varies naturally with event density

If any criterion fails, adjust `[audio.bells]` gains in `ghsingo.toml` and re-render. This is a tuning step — expect 1-3 iterations.

- [ ] **Step 4: Commit any gain adjustments**

```bash
# Only if you adjusted ghsingo.toml:
jj describe -m "tune(ghsingo/audio): adjust bell gains for 5-min listen test"
jj new
```

---

## Task 14: 30-second local video validation

**Files:**
- (No source changes.)

- [ ] **Step 1: Render a short video**

Run: `cd src/ghsingo && timeout 30 $(pwd)/../../ops/bin/live --config ghsingo.toml || true`

Then find the resulting FLV in `../../var/ghsingo/records/`.

Or use:
```bash
cd src/ghsingo && make build-live && timeout 30 ../../ops/bin/live --config ghsingo.toml ; ls -lh ../../var/ghsingo/records/ | tail -5
```

- [ ] **Step 2: Inspect**

Run: `ffprobe -v error -show_format -show_streams ../../var/ghsingo/records/<file>.flv | head -30`
Expected: both video and audio streams present; duration ≈ 30s; audio sample rate 44100; no errors.

Optional listen: `ffplay -autoexit ../../var/ghsingo/records/<file>.flv`
Acceptance: bell audio syncs with on-screen text events; no audio glitches.

- [ ] **Step 3: Advance and push bookmark**

The bookmark was created at Task 1's parent and does not auto-follow new commits, so move it to the latest committed change before pushing:

```bash
jj bookmark set codex/issue-27-bell-era -r @-
jj git push --bookmark codex/issue-27-bell-era
```

Then go to GitHub and open a PR from `codex/issue-27-bell-era` → `main`.

---

## Task 15: Final wrap-up

- [ ] **Step 1: Run full test suite**

Run: `cd src/ghsingo && go test ./... && go vet ./...`
Expected: all green.

- [ ] **Step 2: Update the issue**

Run:
```bash
gh issue comment 27 --body "bell-era implementation landed on codex/issue-27-bell-era.
- 15-pitch pentatonic bell bank pre-rendered
- Clusterer + BellBank + Karplus wired end-to-end
- 5-min MP3 and 30-s video validated
- ghsingo-noisea preserved for rollback

PR: <paste PR URL here>"
```

- [ ] **Step 3: Close issue once PR merges** (manual, done on GitHub)

---

## Notes for the executing engineer

- **jj, not git**: commit with `jj describe -m "..."` then `jj new`. Never `git commit`.
- **Do not push** bookmarks until Task 14 Step 3. Local commits only until the whole chain passes its own tests.
- **Tests first**: every task follows red → green → refactor. Do not skip the failing-test step.
- **No blind auto-format**: run `go fmt ./...` after each task if you like, but don't let it tempt you to batch tasks.
- **If fluidsynth is unavailable**: you can still complete Tasks 1-11. Task 12 (bell bank generation) is the only one that requires it. Without it, the system still runs — BellBank falls back to Karplus synth for all pitches (the 15-sample long-bell layer will simply be absent and rank-1 + Release events use synth instead of samples).
- **The ghsingo-noisea bookmark exists on origin** — do not delete it. It is the fallback.
