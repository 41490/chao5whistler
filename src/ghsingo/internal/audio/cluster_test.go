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
