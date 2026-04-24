package audio

import (
	"os"
	"path/filepath"
	"testing"
)

// minimalWAV returns a valid 16-bit PCM mono WAV containing a short sine fragment.
func minimalWAV(t *testing.T) []byte {
	data := make([]byte, 44+200)
	copy(data[0:], []byte("RIFF"))
	data[4] = 0xEC
	data[5] = 0x00
	data[6] = 0x00
	data[7] = 0x00 // chunk size = 236
	copy(data[8:], []byte("WAVE"))
	copy(data[12:], []byte("fmt "))
	data[16] = 16
	data[20] = 1  // PCM
	data[22] = 1  // mono
	data[24] = 0x44
	data[25] = 0xAC // 44100
	data[32] = 2    // block align
	data[34] = 16   // bits per sample
	copy(data[36:], []byte("data"))
	data[40] = 200
	for i := 0; i < 100; i++ {
		v := int16(1000)
		data[44+i*2] = byte(v)
		data[44+i*2+1] = byte(v >> 8)
	}
	return data
}

func TestBellBankLoadsSamples(t *testing.T) {
	dir := t.TempDir()
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
	var nonzero int
	for i := 0; i < 100; i++ {
		if v.NextSample() != 0 {
			nonzero++
		}
	}
	if nonzero == 0 {
		t.Error("SampleVoice produced only silence")
	}

	if bank.SampleVoice(Pitch{NoteYu, OctaveHigh}, 1.0) != nil {
		t.Error("SampleVoice should return nil when no sample loaded")
	}
}

func TestBellBankSynthVoiceAlwaysAvailable(t *testing.T) {
	bank := NewBellBank(44100)
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
