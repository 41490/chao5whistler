package audio

import (
	"reflect"
	"testing"
)

func testClusterConfig() ClusterConfig {
	return ClusterConfig{
		KeepTopN:        4,
		EventTypeIDs:    []uint8{0, 1, 2, 3, 4}, // Push, Create, Issues, PR, Fork
		AlwaysFireIDs:   []uint8{5},             // ReleaseEvent
		Velocities:      [4]float32{1.00, 0.75, 0.60, 0.45},
		ReleaseVelocity: 1.00,
		OctaveRank1:     OctaveMid,
		OctaveRank2:     []Octave{OctaveMid, OctaveHigh},
		OctaveRank3:     OctaveHigh,
		OctaveRank4:     OctaveLow,
		OctaveRelease:   OctaveHigh,
		SpreadMs:        500,
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
	want := []int{0, 125, 250, 375}
	got := []int{triggers[0].MsOffset, triggers[1].MsOffset, triggers[2].MsOffset, triggers[3].MsOffset}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ms offsets = %v, want %v", got, want)
	}
}

func TestClusterRankMapping(t *testing.T) {
	// Push×2 (rank 1 by count), Create×1 (rank 2 by tie-break ascending TypeID),
	// Issues×1 (rank 3). Order preserved from events:
	//   evs[0] Push    → NoteGong @ OctaveMid
	//   evs[1] Create  → NoteShang @ OctaveMid (rank-2 first occurrence)
	//   evs[2] Push    → NoteGong @ OctaveMid
	//   evs[3] Issues  → NoteJue @ OctaveHigh
	evs := []EventEntry{
		{TypeID: 0}, {TypeID: 1}, {TypeID: 0}, {TypeID: 2},
	}
	triggers := Assign(evs, testClusterConfig())
	if len(triggers) != 4 {
		t.Fatalf("len(triggers) = %d, want 4", len(triggers))
	}
	wantNotes := []Note{NoteGong, NoteShang, NoteGong, NoteJue}
	for i, tr := range triggers {
		if tr.Pitch.Note != wantNotes[i] {
			t.Errorf("trigger %d: note = %v, want %v", i, tr.Pitch.Note, wantNotes[i])
		}
	}
	if triggers[0].Source != SourceSample || triggers[2].Source != SourceSample {
		t.Error("rank-1 triggers should be SourceSample")
	}
	if triggers[1].Source != SourceSynth || triggers[3].Source != SourceSynth {
		t.Error("rank>1 triggers should be SourceSynth")
	}
}

func TestClusterRank2OctaveAlternation(t *testing.T) {
	// Issues×2 (rank 1), Push×2 (rank 2). Push 1st occurrence → OctaveMid,
	// 2nd occurrence → OctaveHigh.
	evs := []EventEntry{
		{TypeID: 2}, {TypeID: 0}, {TypeID: 2}, {TypeID: 0},
	}
	triggers := Assign(evs, testClusterConfig())
	if len(triggers) != 4 {
		t.Fatalf("len = %d, want 4", len(triggers))
	}
	if triggers[1].Pitch.Octave != OctaveMid {
		t.Errorf("Push#1 octave = %v, want OctaveMid", triggers[1].Pitch.Octave)
	}
	if triggers[3].Pitch.Octave != OctaveHigh {
		t.Errorf("Push#2 octave = %v, want OctaveHigh", triggers[3].Pitch.Octave)
	}
}

func TestClusterReleaseAlwaysFires(t *testing.T) {
	evs := []EventEntry{{TypeID: 5}}
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
		{TypeID: 99}, {TypeID: 0},
	}
	triggers := Assign(evs, testClusterConfig())
	if len(triggers) != 1 {
		t.Fatalf("len = %d, want 1 (unknown filtered)", len(triggers))
	}
	if triggers[0].TypeID != 0 {
		t.Error("remaining trigger should be Push")
	}
}

func conductorTestConfig() ClusterConfig {
	c := testClusterConfig()
	c.ConductorMode = true
	c.LeadVelocity = 1.00
	c.BackgroundVelocity = 0.18
	c.WindowMs = 800
	c.WindowJitterMs = 0 // deterministic for tests
	return c
}

func TestConductorEmpty(t *testing.T) {
	if got := Assign(nil, conductorTestConfig()); got != nil {
		t.Errorf("empty input → %v, want nil", got)
	}
}

func TestConductorOneLeadAndBackground(t *testing.T) {
	cfg := conductorTestConfig()
	evs := []EventEntry{
		{TypeID: 0}, // Push (rank 1, count=3)
		{TypeID: 0},
		{TypeID: 0},
		{TypeID: 1}, // Create (rank 2, count=1)
	}
	triggers := Assign(evs, cfg)
	if len(triggers) != 4 {
		t.Fatalf("len = %d, want 4 (1 lead + 3 background)", len(triggers))
	}

	// First trigger is the lead bell (full velocity, sample, NoteGong @ OctaveMid).
	lead := triggers[0]
	if lead.Velocity != 1.00 {
		t.Errorf("lead velocity = %v, want 1.00", lead.Velocity)
	}
	if lead.Source != SourceSample {
		t.Errorf("lead source = %v, want SourceSample", lead.Source)
	}
	if lead.Pitch.Note != NoteGong || lead.Pitch.Octave != OctaveMid {
		t.Errorf("lead pitch = %+v, want NoteGong/OctaveMid", lead.Pitch)
	}
	if lead.WithOcean {
		t.Error("non-Release lead should not carry WithOcean")
	}
	if lead.MsOffset != 0 {
		t.Errorf("lead MsOffset = %d, want 0 (no jitter in test)", lead.MsOffset)
	}

	// Remaining triggers must be background: SourceSynth, velocity scaled below 0.5.
	for i := 1; i < 4; i++ {
		if triggers[i].Source != SourceSynth {
			t.Errorf("bg trigger %d source = %v, want SourceSynth", i, triggers[i].Source)
		}
		if triggers[i].Velocity > 0.5 {
			t.Errorf("bg trigger %d velocity %v not attenuated", i, triggers[i].Velocity)
		}
		if triggers[i].WithOcean {
			t.Errorf("bg trigger %d should not have WithOcean", i)
		}
	}
}

func TestConductorReleaseLeadCarriesOcean(t *testing.T) {
	cfg := conductorTestConfig()
	evs := []EventEntry{{TypeID: 5}} // Release alone
	triggers := Assign(evs, cfg)
	if len(triggers) != 1 {
		t.Fatalf("len = %d, want 1", len(triggers))
	}
	tr := triggers[0]
	if !tr.WithOcean {
		t.Error("Release lead should carry WithOcean=true")
	}
	if tr.Pitch.Note != NoteYu || tr.Pitch.Octave != OctaveHigh {
		t.Errorf("Release lead pitch = %+v, want NoteYu/OctaveHigh", tr.Pitch)
	}
	if tr.Source != SourceSample {
		t.Errorf("Release lead source = %v, want SourceSample", tr.Source)
	}
}

func TestConductorReleaseInBackgroundDoesNotOcean(t *testing.T) {
	cfg := conductorTestConfig()
	// Push×2 dominates; one Release event in the mix → background.
	evs := []EventEntry{
		{TypeID: 0}, {TypeID: 0}, {TypeID: 5},
	}
	triggers := Assign(evs, cfg)
	if len(triggers) != 3 {
		t.Fatalf("len = %d, want 3", len(triggers))
	}
	// Lead is Push (rank 1).
	if triggers[0].WithOcean {
		t.Error("Push lead should not have WithOcean")
	}
	// Find the Release background — it should NOT carry WithOcean.
	for i := 1; i < 3; i++ {
		if triggers[i].TypeID == 5 && triggers[i].WithOcean {
			t.Error("background Release instance should not carry WithOcean (lead-only)")
		}
	}
}

func TestConductorLegacyModePreserved(t *testing.T) {
	cfg := testClusterConfig() // ConductorMode = false (zero value)
	evs := []EventEntry{
		{TypeID: 0}, {TypeID: 0}, {TypeID: 0}, {TypeID: 0},
	}
	triggers := Assign(evs, cfg)
	// Legacy: 4 triggers, all NoteGong, all SourceSample, all velocity 1.00.
	if len(triggers) != 4 {
		t.Fatalf("legacy len = %d, want 4", len(triggers))
	}
	for i, tr := range triggers {
		if tr.Velocity != 1.00 {
			t.Errorf("legacy trigger %d velocity = %v, want 1.00", i, tr.Velocity)
		}
		if tr.Source != SourceSample {
			t.Errorf("legacy trigger %d source = %v, want SourceSample", i, tr.Source)
		}
	}
}

func TestClustererGateSuppressesLead(t *testing.T) {
	cfg := conductorTestConfig()
	cfg.MinStrikeIntervalMs = 1500 // need >1.5s between strikes
	c := NewClusterer(cfg)

	evs := []EventEntry{{TypeID: 0}}

	// Tick 1: starts with msSinceLastStrike very large → fires.
	got1 := c.Tick(evs)
	if len(got1) == 0 {
		t.Fatal("first Tick should fire (no prior strike)")
	}

	// Tick 2: only 1000ms elapsed, gate (1500) blocks → silent.
	got2 := c.Tick(evs)
	if got2 != nil {
		t.Errorf("Tick 2 should be silent (gate); got %v triggers", len(got2))
	}

	// Tick 3: cumulative 2000ms — gate releases.
	got3 := c.Tick(evs)
	if len(got3) == 0 {
		t.Error("Tick 3 should fire (cumulative >= 1500)")
	}
}

func TestClustererGateZeroMeansNoGate(t *testing.T) {
	cfg := conductorTestConfig()
	cfg.MinStrikeIntervalMs = 0 // disabled
	c := NewClusterer(cfg)
	evs := []EventEntry{{TypeID: 0}}
	for i := 0; i < 5; i++ {
		if c.Tick(evs) == nil {
			t.Errorf("with gate=0, every Tick should fire (i=%d)", i)
		}
	}
}

func TestClustererLegacyBypassesGate(t *testing.T) {
	cfg := testClusterConfig()       // ConductorMode = false
	cfg.MinStrikeIntervalMs = 999999 // would block forever in conductor
	c := NewClusterer(cfg)
	evs := []EventEntry{{TypeID: 0}, {TypeID: 0}}
	got := c.Tick(evs)
	if len(got) != 2 {
		t.Errorf("legacy mode should ignore gate; got %d triggers, want 2", len(got))
	}
}

func TestClustererBackgroundZeroSilencesBed(t *testing.T) {
	cfg := conductorTestConfig()
	cfg.BackgroundVelocity = 0.0
	cfg.MinStrikeIntervalMs = 0
	c := NewClusterer(cfg)
	evs := []EventEntry{
		{TypeID: 0}, {TypeID: 0}, {TypeID: 1}, {TypeID: 2},
	}
	got := c.Tick(evs)
	// We still get triggers, but background ones have velocity 0.
	leadCount := 0
	silentBgCount := 0
	for _, tr := range got {
		if tr.Velocity == 0.0 {
			silentBgCount++
		} else {
			leadCount++
		}
	}
	if leadCount != 1 {
		t.Errorf("want exactly 1 audible lead, got %d", leadCount)
	}
	if silentBgCount != len(got)-1 {
		t.Errorf("non-lead triggers should all be silent (vel=0); got silent=%d total=%d", silentBgCount, len(got))
	}
}
