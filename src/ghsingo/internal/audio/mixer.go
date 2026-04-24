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

	active []activeBell

	oceanActive []int

	secondPos    int
	pendingNotes []pendingNote
	frameBuf     []float32
}

type activeBell struct {
	sample *SampleVoice
	synth  *KarplusVoice
	pan    float32
	gain   float32
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

	crossfade := m.sampleRate / 20
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
// The events parameter is accepted for backwards compatibility but is ignored;
// clustering happens upstream via ScheduleNotes.
func (m *Mixer) RenderFrame(_ []struct{ TypeID, Weight uint8 }) []float32 {
	n := m.samplesPerFrame
	if cap(m.frameBuf) < n*2 {
		m.frameBuf = make([]float32, n*2)
	}
	out := m.frameBuf[:n*2]
	clear(out)

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

	if m.beat != nil {
		for i := 0; i < n; i++ {
			s := m.beat.NextSample()
			out[i*2] += s
			out[i*2+1] += s
		}
	}

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

	m.secondPos += n

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
	syn := m.bells.SynthVoice(tr.Pitch, tr.Velocity)
	v = activeBell{synth: syn, pan: pan, gain: m.bellSynthGain, offset: offset}
	m.active = append(m.active, v)
}

// notePan maps a 五声 note to stereo pan position (0=L, 0.5=C, 1=R).
// 宫 centre, 商 偏左, 角 偏右, 徵 远左, 羽 远右.
func notePan(n Note) float32 {
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

// DecodePCM reads WAV bytes and returns interleaved float32 samples.
// Supports 16-bit PCM WAV only.
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

// ApplyFadeOut returns a copy of pcm with a linear fade-out applied to the
// last tailRatio fraction of the samples.
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
