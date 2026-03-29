package audio

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"os"
)

// Mixer mixes a looping BGM track with one-shot voice events into stereo
// interleaved float32 PCM, one video-frame at a time.
type Mixer struct {
	sampleRate      int
	fps             int
	samplesPerFrame int // sampleRate / fps
	bgmPCM          []float32
	bgmGain         float32
	bgmPos          int
	voices          map[uint8]voiceBank // type_id -> WAV samples + gain
	active          []activeVoice       // currently playing instances
}

type voiceBank struct {
	pcm  []float32
	gain float32
}

type activeVoice struct {
	typeID uint8
	weight uint8
	offset int
}

// NewMixer creates a Mixer for the given sample rate and frame rate.
func NewMixer(sampleRate, fps int) *Mixer {
	return &Mixer{
		sampleRate:      sampleRate,
		fps:             fps,
		samplesPerFrame: sampleRate / fps,
		voices:          make(map[uint8]voiceBank),
	}
}

// SetBGM sets the background music track (mono PCM) and its linear gain.
func (m *Mixer) SetBGM(pcm []float32, gain float32) {
	m.bgmPCM = pcm
	m.bgmGain = gain
	m.bgmPos = 0
}

// RegisterVoice registers a one-shot voice sample for the given type ID.
func (m *Mixer) RegisterVoice(typeID uint8, pcm []float32, gain float32) {
	m.voices[typeID] = voiceBank{pcm: pcm, gain: gain}
}

// TriggerEvent starts playback of a registered voice.
func (m *Mixer) TriggerEvent(typeID uint8, weight uint8) {
	if _, ok := m.voices[typeID]; !ok {
		return
	}
	m.active = append(m.active, activeVoice{
		typeID: typeID,
		weight: weight,
		offset: 0,
	})
}

// RenderFrame renders one frame of stereo interleaved PCM float32.
// Returns a slice of length samplesPerFrame*2 (L, R, L, R, ...).
// events can be nil.
func (m *Mixer) RenderFrame(events []struct{ TypeID, Weight uint8 }) []float32 {
	// Process incoming events.
	for _, ev := range events {
		m.TriggerEvent(ev.TypeID, ev.Weight)
	}

	n := m.samplesPerFrame
	out := make([]float32, n*2)

	// 1. BGM (mono → stereo duplicate).
	if len(m.bgmPCM) > 0 {
		for i := 0; i < n; i++ {
			s := m.bgmPCM[m.bgmPos%len(m.bgmPCM)] * m.bgmGain
			out[i*2] += s   // L
			out[i*2+1] += s // R
			m.bgmPos++
		}
	}

	// 2. Active voices.
	for idx := range m.active {
		v := &m.active[idx]
		bank, ok := m.voices[v.typeID]
		if !ok {
			continue
		}
		wf := float32(v.weight) / 255.0
		for i := 0; i < n; i++ {
			if v.offset >= len(bank.pcm) {
				break
			}
			s := bank.pcm[v.offset] * bank.gain * wf
			out[i*2] += s
			out[i*2+1] += s
			v.offset++
		}
	}

	// 3. Remove finished voices.
	alive := m.active[:0]
	for _, v := range m.active {
		bank, ok := m.voices[v.typeID]
		if ok && v.offset < len(bank.pcm) {
			alive = append(alive, v)
		}
	}
	m.active = alive

	// 4. Clamp to [-1.0, 1.0].
	for i := range out {
		if out[i] > 1.0 {
			out[i] = 1.0
		} else if out[i] < -1.0 {
			out[i] = -1.0
		}
	}

	return out
}

// ---------------------------------------------------------------------------
// WAV decoding
// ---------------------------------------------------------------------------

// DecodePCM reads WAV bytes and returns interleaved float32 samples.
// Supports 16-bit PCM WAV only.
func DecodePCM(data []byte) ([]float32, error) {
	if len(data) < 44 {
		return nil, errors.New("audio: data too short for WAV header")
	}

	// RIFF header
	if string(data[0:4]) != "RIFF" {
		return nil, errors.New("audio: missing RIFF tag")
	}
	if string(data[8:12]) != "WAVE" {
		return nil, errors.New("audio: missing WAVE tag")
	}

	// Walk sub-chunks starting at offset 12.
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
			// sampleRate at pos+4..pos+8 (we don't enforce match here)
			bitsPerSample = binary.LittleEndian.Uint16(data[pos+14 : pos+16])
		case "data":
			end := pos + chunkSize
			if end > len(data) {
				end = len(data)
			}
			dataBytes = data[pos:end]
		}

		pos += chunkSize
		// Chunks are word-aligned.
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
	_ = numChannels // channels preserved in interleaved output

	numSamples := len(dataBytes) / 2
	out := make([]float32, numSamples)
	for i := 0; i < numSamples; i++ {
		s := int16(binary.LittleEndian.Uint16(dataBytes[i*2 : i*2+2]))
		out[i] = float32(s) / float32(math.MaxInt16)
	}
	return out, nil
}

// LoadWavFile loads WAV from disk.
func LoadWavFile(path string) ([]float32, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("audio: %w", err)
	}
	return DecodePCM(data)
}

// GainToLinear converts dB to linear: 10^(db/20).
func GainToLinear(db float64) float32 {
	return float32(math.Pow(10, db/20.0))
}
