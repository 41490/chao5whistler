package audio

import "math"

const (
	minBeatBPM        = 60.0
	defaultBeatBPM    = 72.0
	maxBeatBPM        = 120.0
	beatSmoothing     = 0.0001
	beatKickSeconds   = 0.35
	beatKickStartHz   = 82.0
	beatKickEndHz     = 46.0
	beatKickOvertone  = 0.35
	beatKickDecayFast = 12.0
	beatKickDecaySlow = 28.0
)

// BeatGenerator synthesizes a soft bass-drum pulse whose tempo follows
// the recent event density.
type BeatGenerator struct {
	sampleRate int
	currentBPM float64
	targetBPM  float64
	phase      float64
	gain       float32

	kickPhase     float64
	kickAge       int
	kickRemaining int
}

func NewBeatGenerator(sampleRate int, gain float32) *BeatGenerator {
	return &BeatGenerator{
		sampleRate: sampleRate,
		currentBPM: defaultBeatBPM,
		targetBPM:  defaultBeatBPM,
		gain:       gain,
	}
}

// SetDensity updates the target BPM from the last 60 seconds of event counts.
func (b *BeatGenerator) SetDensity(eventsPerMin int) {
	switch {
	case eventsPerMin < 5:
		b.targetBPM = minBeatBPM
	case eventsPerMin < 20:
		b.targetBPM = defaultBeatBPM
	case eventsPerMin < 50:
		b.targetBPM = 90.0
	default:
		b.targetBPM = maxBeatBPM
	}
}

func (b *BeatGenerator) CurrentBPM() float64 {
	return b.currentBPM
}

func (b *BeatGenerator) TargetBPM() float64 {
	return b.targetBPM
}

// NextSample returns the next mono beat sample.
func (b *BeatGenerator) NextSample() float32 {
	if b == nil || b.sampleRate <= 0 || b.gain == 0 {
		return 0
	}

	b.currentBPM += (b.targetBPM - b.currentBPM) * beatSmoothing
	if b.currentBPM < minBeatBPM {
		b.currentBPM = minBeatBPM
	}
	if b.currentBPM > maxBeatBPM {
		b.currentBPM = maxBeatBPM
	}

	b.phase += b.currentBPM / (60.0 * float64(b.sampleRate))
	if b.phase >= 1.0 {
		b.phase -= 1.0
		b.triggerKick()
	}

	return b.kickSample() * b.gain
}

func (b *BeatGenerator) triggerKick() {
	b.kickPhase = 0
	b.kickAge = 0
	b.kickRemaining = int(float64(b.sampleRate) * beatKickSeconds)
}

func (b *BeatGenerator) kickSample() float32 {
	if b.kickRemaining <= 0 {
		return 0
	}

	t := float64(b.kickAge) / float64(b.sampleRate)
	norm := float64(b.kickAge) / float64(maxInt(b.kickRemaining+b.kickAge, 1))
	freq := beatKickStartHz + (beatKickEndHz-beatKickStartHz)*norm
	b.kickPhase += 2.0 * math.Pi * freq / float64(b.sampleRate)

	fastEnv := math.Exp(-beatKickDecayFast * t)
	slowEnv := math.Exp(-beatKickDecaySlow * t)
	fundamental := math.Sin(b.kickPhase) * fastEnv
	overtone := math.Sin(2.0*b.kickPhase) * slowEnv * beatKickOvertone

	b.kickAge++
	b.kickRemaining--

	return float32(fundamental + overtone)
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
