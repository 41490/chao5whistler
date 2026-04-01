package audio

// Reverb implements a simple Schroeder reverb using four parallel comb filters
// followed by two all-pass filters. It gives event sounds an underwater / large
// space quality without external DSP libraries.
//
// Usage:
//
//	r := NewReverb(sampleRate)
//	wetSample := r.Process(drySample)
type Reverb struct {
	combs    [4]combFilter
	allpasses [2]allpassFilter
	wet      float32 // wet mix level (0 = dry only, 1 = wet only)
}

// combFilter is a simple feedback comb filter: delay + feedback gain.
type combFilter struct {
	buf  []float32
	pos  int
	gain float32
}

// allpassFilter is a Schroeder all-pass section.
type allpassFilter struct {
	buf  []float32
	pos  int
	gain float32
}

// NewReverb creates a Reverb for the given sample rate.
// Wet mix defaults to 0.25 (25% reverb).
func NewReverb(sampleRate int) *Reverb {
	// Comb delays (ms) chosen as mutually prime to avoid metallic resonance:
	// 37ms, 41ms, 43ms, 47ms
	combDelaysMs := [4]float64{37, 41, 43, 47}
	combGains := [4]float32{0.80, 0.78, 0.76, 0.74}

	// All-pass delays: 5ms, 1.7ms
	apDelaysMs := [2]float64{5.0, 1.7}
	apGains := [2]float32{0.5, 0.5}

	r := &Reverb{wet: 0.25}

	for i := 0; i < 4; i++ {
		n := int(combDelaysMs[i] * float64(sampleRate) / 1000.0)
		r.combs[i] = combFilter{
			buf:  make([]float32, n),
			gain: combGains[i],
		}
	}
	for i := 0; i < 2; i++ {
		n := int(apDelaysMs[i] * float64(sampleRate) / 1000.0)
		if n < 1 {
			n = 1
		}
		r.allpasses[i] = allpassFilter{
			buf:  make([]float32, n),
			gain: apGains[i],
		}
	}
	return r
}

// SetWet sets the wet/dry mix (0.0 = fully dry, 1.0 = fully wet).
func (r *Reverb) SetWet(wet float32) {
	r.wet = wet
}

// Process applies one sample through the reverb and returns the wet+dry mix.
func (r *Reverb) Process(x float32) float32 {
	// Run four parallel comb filters and sum their output.
	var combSum float32
	for i := range r.combs {
		combSum += r.combs[i].process(x)
	}
	combSum *= 0.25 // normalise

	// Series all-pass filters.
	ap := r.allpasses[0].process(combSum)
	ap = r.allpasses[1].process(ap)

	return x*(1-r.wet) + ap*r.wet
}

// process runs one sample through a comb filter.
func (c *combFilter) process(x float32) float32 {
	out := c.buf[c.pos]
	c.buf[c.pos] = x + out*c.gain
	c.pos = (c.pos + 1) % len(c.buf)
	return out
}

// process runs one sample through an all-pass filter.
func (a *allpassFilter) process(x float32) float32 {
	delayed := a.buf[a.pos]
	out := -x + delayed
	a.buf[a.pos] = x + delayed*a.gain
	a.pos = (a.pos + 1) % len(a.buf)
	return out
}
