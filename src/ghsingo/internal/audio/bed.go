package audio

import "math/rand"

// BedVoice is a long-lived noise pad that supplies the L1 mid-layer
// texture. Pink-ish noise is run through a single-pole lowpass to keep
// it under the drone's brightness, then amplitude-smoothed toward a
// brightness-driven target.
type BedVoice struct {
	sampleRate int
	rng        *rand.Rand

	// Voss-McCartney style pink noise generators (cheap pink approx).
	rows    [5]float32
	counter int

	lp1 float32
	lp2 float32
	a   float32 // lowpass coefficient

	targetGain float32
	gain       float32
	gainSlew   float32
}

// NewBedVoice constructs a bed voice with cutoff ~600 Hz so the texture
// never competes with the accent layer above 1 kHz.
func NewBedVoice(sampleRate int, seed int64) *BedVoice {
	if seed == 0 {
		seed = 0x6361 // arbitrary non-zero default — silent renders are
		// not what we want when callers forget the seed
	}
	return &BedVoice{
		sampleRate: sampleRate,
		rng:        rand.New(rand.NewSource(seed)),
		a:          0.04, // ~600 Hz at 44.1 kHz
		gainSlew:   1.0 / float32(sampleRate) * 3.0,
	}
}

// SetTargetGain sets the smoothed amplitude target.
func (b *BedVoice) SetTargetGain(g float32) {
	if g < 0 {
		g = 0
	}
	if g > 1 {
		g = 1
	}
	b.targetGain = g
}

// NextSample produces one mono pink-noise sample, lowpassed, scaled by
// the smoothed gain.
func (b *BedVoice) NextSample() float32 {
	b.counter++
	for i := 0; i < 5; i++ {
		if b.counter%(1<<i) == 0 {
			b.rows[i] = b.rng.Float32()*2 - 1
		}
	}
	var pink float32
	for _, r := range b.rows {
		pink += r
	}
	pink *= 0.2

	b.lp1 += b.a * (pink - b.lp1)
	b.lp2 += b.a * (b.lp1 - b.lp2)

	if b.gain < b.targetGain {
		b.gain += b.gainSlew
		if b.gain > b.targetGain {
			b.gain = b.targetGain
		}
	} else if b.gain > b.targetGain {
		b.gain -= b.gainSlew
		if b.gain < b.targetGain {
			b.gain = b.targetGain
		}
	}

	return b.lp2 * b.gain
}
