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
