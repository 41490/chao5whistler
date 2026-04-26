package audio

import (
	"math"

	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
)

// DroneVoice is a long-lived continuous oscillator: a sine at the active
// mode's root frequency layered with a sub octave, lightly detuned for
// movement. Amplitude is exponentially smoothed toward TargetGain so the
// drone reacts to the composer's slow state without clicks.
//
// The drone is the L0 floor of the ambient engine (#28/#31): it plays
// every sample, regardless of whether GH events are arriving.
type DroneVoice struct {
	sampleRate int
	phaseRoot  float64
	phaseSub   float64
	phaseLfo   float64
	rootHz     float64
	subHz      float64
	targetGain float32
	gain       float32
	gainSlew   float32
}

// NewDroneVoice initializes the drone in mode Yo at zero gain. Use
// SetMode + SetTargetGain to drive it from composer output.
func NewDroneVoice(sampleRate int) *DroneVoice {
	d := &DroneVoice{
		sampleRate: sampleRate,
		gainSlew:   1.0 / float32(sampleRate) * 4.0, // ~250 ms slew per unit
	}
	d.SetMode(composer.ModeYo)
	return d
}

// SetMode picks a root frequency based on the composer mode. Bright modes
// sit a touch higher; dark modes drop down.
func (d *DroneVoice) SetMode(m composer.Mode) {
	switch m {
	case composer.ModeYo:
		d.rootHz = 220.0 // A3
	case composer.ModeHira:
		d.rootHz = 196.0 // G3
	case composer.ModeIn:
		d.rootHz = 174.61 // F3
	case composer.ModeRyo:
		d.rootHz = 233.08 // Bb3
	default:
		d.rootHz = 220.0
	}
	d.subHz = d.rootHz * 0.5
}

// SetTargetGain sets the slew destination for the drone level.
func (d *DroneVoice) SetTargetGain(g float32) {
	if g < 0 {
		g = 0
	}
	if g > 1 {
		g = 1
	}
	d.targetGain = g
}

// NextSample advances one sample and returns the mono drone output.
func (d *DroneVoice) NextSample() float32 {
	if d.gain < d.targetGain {
		d.gain += d.gainSlew
		if d.gain > d.targetGain {
			d.gain = d.targetGain
		}
	} else if d.gain > d.targetGain {
		d.gain -= d.gainSlew
		if d.gain < d.targetGain {
			d.gain = d.targetGain
		}
	}

	dt := 1.0 / float64(d.sampleRate)
	d.phaseRoot += 2 * math.Pi * d.rootHz * dt
	d.phaseSub += 2 * math.Pi * d.subHz * dt
	d.phaseLfo += 2 * math.Pi * 0.1 * dt
	if d.phaseRoot > 2*math.Pi {
		d.phaseRoot -= 2 * math.Pi
	}
	if d.phaseSub > 2*math.Pi {
		d.phaseSub -= 2 * math.Pi
	}
	if d.phaseLfo > 2*math.Pi {
		d.phaseLfo -= 2 * math.Pi
	}

	lfo := 0.5 + 0.5*math.Sin(d.phaseLfo)
	root := math.Sin(d.phaseRoot) * 0.5
	sub := math.Sin(d.phaseSub) * 0.6
	mix := (root + sub) * (0.7 + 0.3*lfo)
	return float32(mix) * d.gain
}
