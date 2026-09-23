package audio

// TonalBedVoice plays a long-form tonal sample as a continuously looped
// L0.5 bed between the synth drone (L0) and the noise bed (L1). Unlike
// the legacy BGM path it is not a "background music track" — it is one
// of three always-on ambient layers sharing the same space and master.
//
// The voice loops with a short crossfade (default 50 ms) to hide the
// loop boundary and applies a single-pole lowpass plus an exponentially
// smoothed gain so #31's MixerV2 can modulate the bed from composer
// state without clicks.
type TonalBedVoice struct {
	pcm        []float32
	pos        int
	crossfade  int
	lp         float32
	a          float32
	gain       float32
	targetGain float32
	gainSlew   float32
}

// NewTonalBedVoice builds a TonalBedVoice from mono PCM. Pass an empty
// slice or nil to disable the layer; in that case NextSample returns 0.
func NewTonalBedVoice(sampleRate int, pcm []float32) *TonalBedVoice {
	t := &TonalBedVoice{
		pcm:       pcm,
		crossfade: sampleRate / 20,         // 50 ms
		a:         0.10,                    // ~1.5 kHz lowpass
		gainSlew:  1.0 / float32(sampleRate) * 4.0,
	}
	if t.crossfade > len(pcm)/2 {
		t.crossfade = len(pcm) / 2
	}
	return t
}

// SetTargetGain queues a new gain target (smoothed over ~250 ms).
func (t *TonalBedVoice) SetTargetGain(g float32) {
	if g < 0 {
		g = 0
	}
	if g > 1 {
		g = 1
	}
	t.targetGain = g
}

// NextSample advances one sample and returns the lowpassed bed output.
// Returns 0 when the underlying PCM is empty.
func (t *TonalBedVoice) NextSample() float32 {
	if len(t.pcm) == 0 {
		return 0
	}
	loopLen := len(t.pcm)
	pos := t.pos % loopLen
	s := t.pcm[pos]

	if t.crossfade > 0 && t.crossfade < loopLen/2 {
		tail := loopLen - t.crossfade
		if pos >= tail {
			fadeOut := float32(loopLen-pos) / float32(t.crossfade)
			fadeIn := 1.0 - fadeOut
			headPos := pos - tail
			s = s*fadeOut + t.pcm[headPos]*fadeIn
		}
	}
	t.pos++

	t.lp += t.a * (s - t.lp)

	if t.gain < t.targetGain {
		t.gain += t.gainSlew
		if t.gain > t.targetGain {
			t.gain = t.targetGain
		}
	} else if t.gain > t.targetGain {
		t.gain -= t.gainSlew
		if t.gain < t.targetGain {
			t.gain = t.targetGain
		}
	}

	return t.lp * t.gain
}
