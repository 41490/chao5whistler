package audio

import "math/rand"

// KarplusVoice is a one-shot Karplus-Strong plucked-string voice tuned for
// short bell-like attacks. A fresh voice is allocated per trigger.
type KarplusVoice struct {
	buf       []float32
	pos       int
	decay     float64
	remaining int
	velocity  float32
}

// NewKarplusVoice starts a bell ring at the given frequency. decay should be
// 0.99~0.999 (higher = longer ring). velocity scales the initial excitation.
// Auto-silences after ~2 seconds regardless of decay (safety cap).
func NewKarplusVoice(sampleRate int, freq float64, decay float64, velocity float32) *KarplusVoice {
	n := int(float64(sampleRate) / freq)
	if n < 2 {
		n = 2
	}
	buf := make([]float32, n)
	for i := range buf {
		buf[i] = (rand.Float32()*2 - 1) * velocity
	}
	return &KarplusVoice{
		buf:       buf,
		decay:     decay,
		remaining: sampleRate * 2,
		velocity:  velocity,
	}
}

// NextSample returns one sample and advances the voice state.
func (v *KarplusVoice) NextSample() float32 {
	if v.remaining <= 0 {
		return 0
	}
	out := v.buf[v.pos]
	next := (v.pos + 1) % len(v.buf)
	averaged := (v.buf[v.pos] + v.buf[next]) * 0.5
	v.buf[v.pos] = float32(float64(averaged) * v.decay)
	v.pos = next
	v.remaining--
	return out
}

// Done reports whether the voice has stopped producing audio.
func (v *KarplusVoice) Done() bool {
	return v.remaining <= 0
}
