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
	// OctaveLow is the lowest octave band (C3~A3).
	OctaveLow Octave = 0
	// OctaveMid is the middle octave band (C4~A4).
	OctaveMid Octave = 1
	// OctaveHigh is the highest octave band (C5~A5).
	OctaveHigh Octave = 2
)

// OctaveCount is the number of octave bands.
const OctaveCount = 3

// Pitch is a (note, octave) pair, one of 15 grid points.
type Pitch struct {
	Note   Note
	Octave Octave
}

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
	default:
		// default: invalid octave → fall back to base octave
		return base
	}
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
