package audio

import (
	"encoding/binary"
	"math"
	"testing"
)

// generateTestWAV creates a minimal valid 16-bit PCM WAV with a 440 Hz sine wave.
func generateTestWAV(sampleRate, channels, numSamples int) []byte {
	bytesPerSample := 2
	dataSize := numSamples * channels * bytesPerSample
	fileSize := 36 + dataSize // 44 byte header - 8 for RIFF+size

	buf := make([]byte, 44+dataSize)

	// RIFF header
	copy(buf[0:4], "RIFF")
	binary.LittleEndian.PutUint32(buf[4:8], uint32(fileSize))
	copy(buf[8:12], "WAVE")

	// fmt sub-chunk
	copy(buf[12:16], "fmt ")
	binary.LittleEndian.PutUint32(buf[16:20], 16) // chunk size
	binary.LittleEndian.PutUint16(buf[20:22], 1)  // PCM
	binary.LittleEndian.PutUint16(buf[22:24], uint16(channels))
	binary.LittleEndian.PutUint32(buf[24:28], uint32(sampleRate))
	blockAlign := channels * bytesPerSample
	binary.LittleEndian.PutUint32(buf[28:32], uint32(sampleRate*blockAlign)) // byte rate
	binary.LittleEndian.PutUint16(buf[32:34], uint16(blockAlign))
	binary.LittleEndian.PutUint16(buf[34:36], uint16(bytesPerSample*8)) // bits per sample

	// data sub-chunk
	copy(buf[36:40], "data")
	binary.LittleEndian.PutUint32(buf[40:44], uint32(dataSize))

	// Generate 440 Hz sine wave samples.
	offset := 44
	for i := 0; i < numSamples; i++ {
		val := math.Sin(2.0 * math.Pi * 440.0 * float64(i) / float64(sampleRate))
		s := int16(val * float64(math.MaxInt16))
		for ch := 0; ch < channels; ch++ {
			binary.LittleEndian.PutUint16(buf[offset:offset+2], uint16(s))
			offset += 2
		}
	}

	return buf
}

func TestLoadWavSamples(t *testing.T) {
	// 0.1 s stereo at 44100 Hz → 4410 samples × 2 channels = 8820 float32 values.
	sampleRate := 44100
	numSamples := sampleRate / 10 // 4410
	channels := 2

	wav := generateTestWAV(sampleRate, channels, numSamples)
	pcm, err := DecodePCM(wav)
	if err != nil {
		t.Fatalf("DecodePCM error: %v", err)
	}

	expected := numSamples * channels // 8820
	if len(pcm) != expected {
		t.Fatalf("expected %d samples, got %d", expected, len(pcm))
	}

	// Sanity: samples should not all be zero (sine wave).
	allZero := true
	for _, s := range pcm {
		if s != 0 {
			allZero = false
			break
		}
	}
	if allZero {
		t.Fatal("all samples are zero; expected sine wave data")
	}
}

func TestMixerBGMLoop(t *testing.T) {
	m := NewMixer(44100, 30) // samplesPerFrame = 1470

	// 100-sample mono BGM: constant 0.5.
	bgm := make([]float32, 100)
	for i := range bgm {
		bgm[i] = 0.5
	}
	m.SetBGM(bgm, 1.0)

	out := m.RenderFrame(nil)
	if len(out) != 1470*2 {
		t.Fatalf("expected %d output samples, got %d", 1470*2, len(out))
	}

	// First L sample should be ≈ 0.5.
	if math.Abs(float64(out[0])-0.5) > 1e-6 {
		t.Errorf("first L sample = %f, want ≈ 0.5", out[0])
	}
	// First R sample should also be ≈ 0.5.
	if math.Abs(float64(out[1])-0.5) > 1e-6 {
		t.Errorf("first R sample = %f, want ≈ 0.5", out[1])
	}

	// Verify looping: sample at index 100 should wrap and equal bgm[0]*gain.
	idx := 100
	if math.Abs(float64(out[idx*2])-0.5) > 1e-6 {
		t.Errorf("sample at wrap point = %f, want ≈ 0.5", out[idx*2])
	}
}

func TestMixerVoiceTrigger(t *testing.T) {
	m := NewMixer(44100, 30)

	// Register a short voice: 500 samples of constant 0.7.
	voice := make([]float32, 500)
	for i := range voice {
		voice[i] = 0.7
	}
	m.RegisterVoice(0, voice, 1.0)

	// Trigger with weight 128.
	events := []struct{ TypeID, Weight uint8 }{
		{TypeID: 0, Weight: 128},
	}
	out := m.RenderFrame(events)

	// Output should be non-zero.
	nonZero := false
	for _, s := range out {
		if s != 0 {
			nonZero = true
			break
		}
	}
	if !nonZero {
		t.Fatal("output is all zeros after voice trigger")
	}

	// Verify first sample: 0.7 * 1.0 * (128/255).
	expected := float32(0.7) * (128.0 / 255.0)
	if math.Abs(float64(out[0])-float64(expected)) > 1e-5 {
		t.Errorf("first L sample = %f, want ≈ %f", out[0], expected)
	}
}

func TestMixerClamp(t *testing.T) {
	m := NewMixer(44100, 30)

	// Loud BGM: constant 0.9.
	bgm := make([]float32, 2000)
	for i := range bgm {
		bgm[i] = 0.9
	}
	m.SetBGM(bgm, 1.0)

	// Loud voice: constant 0.9.
	voice := make([]float32, 2000)
	for i := range voice {
		voice[i] = 0.9
	}
	m.RegisterVoice(0, voice, 1.0)

	events := []struct{ TypeID, Weight uint8 }{
		{TypeID: 0, Weight: 255},
	}
	out := m.RenderFrame(events)

	for i, s := range out {
		if s > 1.0 {
			t.Fatalf("sample[%d] = %f exceeds 1.0", i, s)
		}
		if s < -1.0 {
			t.Fatalf("sample[%d] = %f below -1.0", i, s)
		}
	}

	// Combined would be 0.9 + 0.9*(255/255) = 1.8 without clamping.
	// Verify clamping actually engaged on the first sample.
	if out[0] != 1.0 {
		t.Errorf("expected clamped sample = 1.0, got %f", out[0])
	}
}

func TestGainToLinear(t *testing.T) {
	// 0 dB → 1.0
	g := GainToLinear(0)
	if math.Abs(float64(g)-1.0) > 1e-6 {
		t.Errorf("GainToLinear(0) = %f, want 1.0", g)
	}
	// -20 dB → 0.1
	g = GainToLinear(-20)
	if math.Abs(float64(g)-0.1) > 1e-3 {
		t.Errorf("GainToLinear(-20) = %f, want ≈ 0.1", g)
	}
}
