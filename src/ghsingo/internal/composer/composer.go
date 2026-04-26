// Package composer implements the v1 state-vector composer described in
// issue #30 (parent #28). It replaces the bell-era "every event becomes a
// note" model with a slow-moving musical state that downstream layers
// (long-lived buses, sparse accents, mode-aware voices) can consume.
//
// Core invariant for DoD #30: high event density only perturbs the slow
// state (Density/Brightness EMAs); it does NOT scale accent emission. The
// accent stream is governed by an independent phrase scheduler so that a
// 50× burst of GH activity does not turn into a 50× barrage of audible
// strikes — exactly the failure mode #28 was opened to fix.
//
// This package is pure logic: no audio, no toml, no I/O. The `cmd/composer-demo`
// program drives it against a daypack and emits a JSON state timeline that
// #31 (mixer v2) and reviewers can inspect.
package composer

import (
	"math/rand"
	"time"
)

// Mode is a pentatonic-family selection. The slow state currently drifts
// across four modes; mappings to actual pitches happen in voice/L2 layers.
type Mode int

const (
	ModeYo   Mode = iota // bright major-pentatonic flavor
	ModeHira             // calm mid pentatonic
	ModeIn               // dark / contemplative pentatonic
	ModeRyo              // tense / ceremonial pentatonic
)

func (m Mode) String() string {
	switch m {
	case ModeYo:
		return "yo"
	case ModeHira:
		return "hira"
	case ModeIn:
		return "in"
	case ModeRyo:
		return "ryo"
	}
	return "unknown"
}

// Section is the long-period phrase state. It cycles deterministically:
// Rest -> Build -> Flow -> Ebb -> Rest. Each section gates accent
// probability via SectionMultiplier.
type Section int

const (
	SectionRest Section = iota
	SectionBuild
	SectionFlow
	SectionEbb
)

func (s Section) String() string {
	switch s {
	case SectionRest:
		return "rest"
	case SectionBuild:
		return "build"
	case SectionFlow:
		return "flow"
	case SectionEbb:
		return "ebb"
	}
	return "unknown"
}

// State is the slow-moving musical state at the end of a tick. All EMA
// values are in [0, 1].
type State struct {
	Density       float64 `json:"density"`
	Brightness    float64 `json:"brightness"`
	Mode          Mode    `json:"-"`
	ModeName      string  `json:"mode"`
	Section       Section `json:"-"`
	SectionName   string  `json:"section"`
	AccentProb    float64 `json:"accent_prob"`
	TicksInPhrase int     `json:"ticks_in_phrase"`
}

// Event is one GH event arrival in the current tick. Only TypeID and
// Weight are needed; richer event metadata stays in the archive.
type Event struct {
	TypeID uint8
	Weight uint8
}

// Accent is a sparse "L2" trigger emitted occasionally by the phrase
// scheduler. The composer chooses degree (0..4 within the active mode)
// and a tentative octave; concrete voice selection happens downstream
// (#31 mixer v2 / #32 stems).
type Accent struct {
	Velocity  float64 `json:"velocity"`
	Degree    int     `json:"degree"`
	Octave    int     `json:"octave"`
	FromMode  Mode    `json:"-"`
	ModeName  string  `json:"mode"`
}

// Output is what one Tick returns: the new slow state and 0+ sparse accents.
type Output struct {
	State   State    `json:"state"`
	Accents []Accent `json:"accents,omitempty"`
}

// Config tunes the composer. Zero values fall back to vetted defaults so
// callers can construct a Composer with `composer.New(composer.Config{})`.
type Config struct {
	// EMAAlpha is the per-tick weight on the new sample (0..1). Smaller =
	// slower drift. Default 0.06 (~16-tick half-life).
	EMAAlpha float64

	// DensitySaturation is the events-per-tick that maps to Density=1.0.
	// Bursts above this saturate. Default 12.
	DensitySaturation float64

	// BrightnessSaturation is the average event weight that maps to
	// Brightness=1.0. Default 80 (Fork/Release-class).
	BrightnessSaturation float64

	// PhraseTicks is the number of ticks per phrase before a section
	// transition. Default 16.
	PhraseTicks int

	// AccentCooldownTicks is the minimum ticks between accents. Default 3.
	AccentCooldownTicks int

	// AccentBaseProb is the per-tick base probability before section
	// multiplier. Default 0.10.
	AccentBaseProb float64

	// Seed for deterministic behavior. 0 -> time.Now().UnixNano().
	Seed int64
}

func (c *Config) applyDefaults() {
	if c.EMAAlpha <= 0 {
		c.EMAAlpha = 0.06
	}
	if c.DensitySaturation <= 0 {
		c.DensitySaturation = 12
	}
	if c.BrightnessSaturation <= 0 {
		c.BrightnessSaturation = 80
	}
	if c.PhraseTicks <= 0 {
		c.PhraseTicks = 16
	}
	if c.AccentCooldownTicks < 0 {
		c.AccentCooldownTicks = 0
	}
	if c.AccentCooldownTicks == 0 {
		c.AccentCooldownTicks = 3
	}
	if c.AccentBaseProb <= 0 {
		c.AccentBaseProb = 0.10
	}
}

// Composer is the stateful state-vector composer. One instance per render.
type Composer struct {
	cfg           Config
	state         State
	rng           *rand.Rand
	cooldown      int
	ticksInPhrase int
	totalTicks    int
}

// New constructs a Composer. Initial state: Section=Rest, Mode=Yo, all EMAs zero.
func New(cfg Config) *Composer {
	cfg.applyDefaults()
	seed := cfg.Seed
	if seed == 0 {
		seed = time.Now().UnixNano()
	}
	c := &Composer{
		cfg: cfg,
		rng: rand.New(rand.NewSource(seed)),
		state: State{
			Mode:        ModeYo,
			ModeName:    ModeYo.String(),
			Section:     SectionRest,
			SectionName: SectionRest.String(),
		},
	}
	c.state.AccentProb = c.cfg.AccentBaseProb * sectionMultiplier(c.state.Section)
	return c
}

// Tick advances the composer by one tick (= one data-second). It folds
// the events into the slow state and decides whether to emit an accent.
//
// Critically, accent emission is governed by the phrase scheduler and
// the rng, NOT by len(events). This is the architectural property that
// distinguishes #30 from the bell-era trigger model.
func (c *Composer) Tick(events []Event) Output {
	rawDensity := float64(len(events)) / c.cfg.DensitySaturation
	if rawDensity > 1 {
		rawDensity = 1
	}

	var rawBright float64
	if len(events) > 0 {
		var sum float64
		for _, e := range events {
			sum += float64(e.Weight)
		}
		rawBright = sum / float64(len(events)) / c.cfg.BrightnessSaturation
		if rawBright > 1 {
			rawBright = 1
		}
	}

	a := c.cfg.EMAAlpha
	c.state.Density = c.state.Density*(1-a) + rawDensity*a
	c.state.Brightness = c.state.Brightness*(1-a) + rawBright*a

	c.ticksInPhrase++
	if c.ticksInPhrase >= c.cfg.PhraseTicks {
		c.advanceSection()
		c.ticksInPhrase = 0
	}

	prob := c.cfg.AccentBaseProb * sectionMultiplier(c.state.Section)
	c.state.AccentProb = prob

	var accents []Accent
	if c.cooldown > 0 {
		c.cooldown--
	} else if c.rng.Float64() < prob {
		accents = []Accent{c.makeAccent()}
		c.cooldown = c.cfg.AccentCooldownTicks
	}

	c.state.TicksInPhrase = c.ticksInPhrase
	c.state.ModeName = c.state.Mode.String()
	c.state.SectionName = c.state.Section.String()
	c.totalTicks++

	return Output{State: c.state, Accents: accents}
}

func (c *Composer) advanceSection() {
	c.state.Section = nextSection(c.state.Section)
	// Mode drift fires on entry to Flow only — keeps the harmonic identity
	// stable across the Build/Ebb/Rest stretch.
	if c.state.Section == SectionFlow {
		c.state.Mode = pickMode(c.state.Brightness, c.rng)
	}
}

func (c *Composer) makeAccent() Accent {
	vel := 0.55 + 0.45*c.state.Brightness
	octave := 4
	switch {
	case c.state.Brightness > 0.66:
		octave = 5
	case c.state.Brightness < 0.33:
		octave = 3
	}
	return Accent{
		Velocity: vel,
		Degree:   c.rng.Intn(5),
		Octave:   octave,
		FromMode: c.state.Mode,
		ModeName: c.state.Mode.String(),
	}
}

func nextSection(s Section) Section {
	switch s {
	case SectionRest:
		return SectionBuild
	case SectionBuild:
		return SectionFlow
	case SectionFlow:
		return SectionEbb
	case SectionEbb:
		return SectionRest
	}
	return SectionRest
}

func sectionMultiplier(s Section) float64 {
	switch s {
	case SectionRest:
		return 0.0
	case SectionBuild:
		return 1.5
	case SectionFlow:
		return 3.0
	case SectionEbb:
		return 1.0
	}
	return 0
}

func pickMode(brightness float64, rng *rand.Rand) Mode {
	// Bias mode selection by brightness, but keep a small wandering chance
	// so the choice never feels mechanically determined.
	r := rng.Float64()
	switch {
	case brightness > 0.66:
		if r < 0.7 {
			return ModeYo
		}
		if r < 0.9 {
			return ModeRyo
		}
		return ModeHira
	case brightness > 0.33:
		if r < 0.5 {
			return ModeHira
		}
		if r < 0.8 {
			return ModeYo
		}
		return ModeIn
	default:
		if r < 0.6 {
			return ModeIn
		}
		if r < 0.85 {
			return ModeHira
		}
		return ModeRyo
	}
}
