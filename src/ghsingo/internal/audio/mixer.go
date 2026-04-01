package audio

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"math/rand"
	"os"
	"sort"
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

	// Drum layer: single-shot sample triggered at fixed BPM intervals.
	drumPCM          []float32
	drumGain         float32
	drumIntervalSamp int // samples between beats
	drumPhase        int // counts up to drumIntervalSamp, then resets and fires
	drumOffset       int // playback position within current drum hit (-1 = idle)

	// per-second scheduling: events queued with a sample-offset within the second
	secondPos  int            // sample counter within current second (0 .. sampleRate-1)
	pendingEvs []pendingVoice // sorted by triggerAt
}

type voiceBank struct {
	pcm  []float32
	gain float32
}

// activeVoice is a playing instance of a voice sample.
// age counts completed seconds since the event was scheduled (0 = current second).
type activeVoice struct {
	typeID uint8
	weight uint8
	offset int
	age    int // doppler factor: gain *= 1/(1+age)
}

// pendingVoice is a scheduled-but-not-yet-triggered event.
type pendingVoice struct {
	typeID    uint8
	weight    uint8
	triggerAt int // sample offset within the current second at which to fire
	age       int
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

// SetDrum configures a repeating drum hit at the given BPM.
// The PCM sample plays from the start on every beat; the gain is linear.
func (m *Mixer) SetDrum(pcm []float32, gain float32, bpm float64) {
	m.drumPCM = pcm
	m.drumGain = gain
	m.drumIntervalSamp = int(float64(m.sampleRate) * 60.0 / bpm)
	m.drumPhase = 0
	m.drumOffset = 0 // start with a hit on the first beat
}

// TriggerEvent starts playback of a registered voice immediately.
func (m *Mixer) TriggerEvent(typeID uint8, weight uint8) {
	if _, ok := m.voices[typeID]; !ok {
		return
	}
	m.active = append(m.active, activeVoice{
		typeID: typeID,
		weight: weight,
		offset: 0,
		age:    0,
	})
}

// ScheduleSecond queues this second's events for staggered playback.
// Events fire within the first 500 ms of the second at random offsets,
// weighted so heavier events trigger slightly earlier.
// Call this once per second (before rendering frames for that second).
func (m *Mixer) ScheduleSecond(events []struct{ TypeID, Weight uint8 }) {
	// Age all still-active voices from previous seconds.
	for i := range m.active {
		m.active[i].age++
	}
	// Reset per-second position.
	m.secondPos = 0
	m.pendingEvs = m.pendingEvs[:0]

	halfSec := m.sampleRate / 2 // 22050 samples = 500 ms

	for _, ev := range events {
		if _, ok := m.voices[ev.TypeID]; !ok {
			continue
		}
		// Higher weight → earlier in the window (more "important" = closer).
		// weight 255 → offset near 0; weight 0 → offset near 500 ms.
		maxOff := halfSec - halfSec*int(ev.Weight)/255
		var off int
		if maxOff > 0 {
			off = rand.Intn(maxOff + 1)
		}
		m.pendingEvs = append(m.pendingEvs, pendingVoice{
			typeID:    ev.TypeID,
			weight:    ev.Weight,
			triggerAt: off,
			age:       0,
		})
	}
	sort.Slice(m.pendingEvs, func(i, j int) bool {
		return m.pendingEvs[i].triggerAt < m.pendingEvs[j].triggerAt
	})
}

// RenderFrame renders one frame of stereo interleaved PCM float32.
// Returns a slice of length samplesPerFrame*2 (L, R, L, R, ...).
// events can be nil (legacy immediate-trigger path, still supported).
func (m *Mixer) RenderFrame(events []struct{ TypeID, Weight uint8 }) []float32 {
	// Legacy: immediate trigger path.
	for _, ev := range events {
		m.TriggerEvent(ev.TypeID, ev.Weight)
	}

	n := m.samplesPerFrame
	out := make([]float32, n*2)

	// 1. BGM (mono → stereo duplicate).
	if len(m.bgmPCM) > 0 {
		// Sidechain ducking: more active voices → quieter BGM (up to -50%).
		activeCount := float32(len(m.active))
		duckFactor := float32(1.0) - clamp01(activeCount/4.0)*0.5
		effectiveBGMGain := m.bgmGain * duckFactor

		for i := 0; i < n; i++ {
			s := m.bgmPCM[m.bgmPos%len(m.bgmPCM)] * effectiveBGMGain
			out[i*2] += s   // L
			out[i*2+1] += s // R
			m.bgmPos++
		}
	}

	// 2. Drum layer: center-panned, fires at BPM intervals.
	if len(m.drumPCM) > 0 {
		for i := 0; i < n; i++ {
			// Advance phase; when it crosses the interval, start a new hit.
			m.drumPhase++
			if m.drumPhase >= m.drumIntervalSamp {
				m.drumPhase = 0
				m.drumOffset = 0
			}
			// Play the drum sample if active.
			if m.drumOffset >= 0 && m.drumOffset < len(m.drumPCM) {
				s := m.drumPCM[m.drumOffset] * m.drumGain
				out[i*2] += s   // L centre
				out[i*2+1] += s // R centre
				m.drumOffset++
			}
		}
	}

	// 4. Fire pending scheduled events whose triggerAt falls within this frame.
	frameEnd := m.secondPos + n
	remaining := m.pendingEvs[:0]
	for _, pv := range m.pendingEvs {
		if pv.triggerAt < frameEnd {
			// Compute offset within this frame.
			frameOff := pv.triggerAt - m.secondPos
			if frameOff < 0 {
				frameOff = 0
			}
			m.active = append(m.active, activeVoice{
				typeID: pv.typeID,
				weight: pv.weight,
				offset: -frameOff, // negative offset = start mid-frame
				age:    pv.age,
			})
		} else {
			remaining = append(remaining, pv)
		}
	}
	m.pendingEvs = remaining

	// 5. Active voices — stereo panning + doppler gain decay.
	for idx := range m.active {
		v := &m.active[idx]
		bank, ok := m.voices[v.typeID]
		if !ok {
			continue
		}
		wf := float32(v.weight) / 255.0
		// Doppler distance: each aged second halves the volume.
		ageFactor := float32(1.0) / float32(1+v.age)
		finalGain := bank.gain * wf * ageFactor

		// Stereo pan per event type.
		pan := voicePan(v.typeID) // 0.0=left, 0.5=center, 1.0=right
		gainL := finalGain * (1.0 - pan)
		gainR := finalGain * pan

		for i := 0; i < n; i++ {
			pcmIdx := v.offset + i
			if pcmIdx < 0 {
				continue
			}
			if pcmIdx >= len(bank.pcm) {
				break
			}
			s := bank.pcm[pcmIdx]
			out[i*2] += s * gainL
			out[i*2+1] += s * gainR
		}
		v.offset += n
	}

	// 6. Advance per-second position.
	m.secondPos += n

	// 7. Remove finished voices.
	alive := m.active[:0]
	for _, v := range m.active {
		bank, ok := m.voices[v.typeID]
		if ok && v.offset < len(bank.pcm) {
			alive = append(alive, v)
		}
	}
	m.active = alive

	// 8. Soft clipping (tanh) instead of hard clip to avoid harsh distortion.
	for i := range out {
		out[i] = softClip(out[i])
	}

	return out
}

// voicePan returns the stereo pan position for an event type.
// 0.0 = full left, 0.5 = center, 1.0 = full right.
func voicePan(typeID uint8) float32 {
	// PushEvent=0, CreateEvent=1, IssuesEvent=2,
	// PullRequestEvent=3, ForkEvent=4, ReleaseEvent=5
	pans := [6]float32{0.30, 0.70, 0.40, 0.60, 0.20, 0.80}
	if int(typeID) < len(pans) {
		return pans[typeID]
	}
	return 0.5
}

// softClip applies a tanh-based soft limiter: keeps the signal below ±1.0
// with a gentler transition than hard clipping.
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
