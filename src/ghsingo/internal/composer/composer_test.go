package composer

import (
	"testing"
)

// genEvents fabricates a stream of n events per tick, all of one type/weight.
func genEvents(n int, weight uint8) []Event {
	out := make([]Event, n)
	for i := range out {
		out[i] = Event{TypeID: 0, Weight: weight}
	}
	return out
}

// runFor drives a composer for `ticks` ticks with a constant per-tick event
// list and returns the total accent count + final state.
func runFor(seed int64, ticks int, perTick []Event) (int, State) {
	c := New(Config{Seed: seed})
	accents := 0
	var final State
	for i := 0; i < ticks; i++ {
		o := c.Tick(perTick)
		accents += len(o.Accents)
		final = o.State
	}
	return accents, final
}

// TestAccentDecoupledFromDensity is the architectural DoD for #30:
// driving the same composer at vastly different event densities must NOT
// change the accent emission count when the seed is held constant.
func TestAccentDecoupledFromDensity(t *testing.T) {
	const seed = 42
	const ticks = 240 // 4 minutes of data-time

	low, _ := runFor(seed, ticks, genEvents(1, 30))
	high, _ := runFor(seed, ticks, genEvents(50, 30))

	if low != high {
		t.Fatalf("accent count changed with density: low=%d high=%d (must be equal — DoD #30)", low, high)
	}
	if low == 0 {
		t.Fatal("expected at least some accents over 240 ticks")
	}
}

// TestDensityEMARises confirms higher event load actually shows up in the
// slow state — the half of the contract that bell-era ignored.
func TestDensityEMARises(t *testing.T) {
	const seed = 42
	const ticks = 120

	_, lowState := runFor(seed, ticks, genEvents(1, 30))
	_, highState := runFor(seed, ticks, genEvents(50, 30))

	if highState.Density <= lowState.Density {
		t.Fatalf("high-density Density EMA must exceed low: low=%.3f high=%.3f", lowState.Density, highState.Density)
	}
	if highState.Density < 0.5 {
		t.Errorf("high-density Density should saturate near 1.0, got %.3f", highState.Density)
	}
	if lowState.Density > 0.2 {
		t.Errorf("low-density Density should stay near 0, got %.3f", lowState.Density)
	}
}

// TestBrightnessFollowsWeight: heavy events (Release-class weight) push
// Brightness up; light events keep it near zero.
func TestBrightnessFollowsWeight(t *testing.T) {
	const seed = 7
	const ticks = 120

	_, lightState := runFor(seed, ticks, genEvents(3, 20))
	_, heavyState := runFor(seed, ticks, genEvents(3, 100))

	if heavyState.Brightness <= lightState.Brightness {
		t.Fatalf("heavy weight must raise Brightness above light: light=%.3f heavy=%.3f",
			lightState.Brightness, heavyState.Brightness)
	}
}

// TestSectionCyclesDeterministically: with PhraseTicks=4 we should cycle
// through Rest -> Build -> Flow -> Ebb -> Rest within 16 ticks.
func TestSectionCyclesDeterministically(t *testing.T) {
	c := New(Config{Seed: 1, PhraseTicks: 4, AccentCooldownTicks: 100})
	// Section advances at the end of the Nth tick of each phrase, so the
	// state observed after every 4 ticks is the section we just entered.
	wantSeq := []Section{
		SectionBuild, // after ticks 1-4
		SectionFlow,  // after ticks 5-8
		SectionEbb,   // after ticks 9-12
		SectionRest,  // after ticks 13-16
		SectionBuild, // after ticks 17-20
	}
	got := []Section{}
	for phrase := 0; phrase < 5; phrase++ {
		var s Section
		for i := 0; i < 4; i++ {
			out := c.Tick(nil)
			s = out.State.Section
		}
		got = append(got, s)
	}
	for i, want := range wantSeq {
		if got[i] != want {
			t.Errorf("phrase %d: got section %s, want %s", i, got[i], want)
		}
	}
}

// TestRestSectionEmitsNoAccents: SectionRest has multiplier 0, so even with
// favorable rng, no accents should fire while we're in Rest.
func TestRestSectionEmitsNoAccents(t *testing.T) {
	// PhraseTicks large -> we stay in Rest the entire run.
	c := New(Config{Seed: 1, PhraseTicks: 10_000, AccentCooldownTicks: 1, AccentBaseProb: 1.0})
	for i := 0; i < 200; i++ {
		o := c.Tick(genEvents(5, 100))
		if len(o.Accents) > 0 {
			t.Fatalf("Rest section emitted accent at tick %d (multiplier=0)", i)
		}
	}
}

// TestAccentCooldownEnforced: with a 5-tick cooldown and prob=1, accents
// must be at least 5 ticks apart.
func TestAccentCooldownEnforced(t *testing.T) {
	c := New(Config{
		Seed:                1,
		PhraseTicks:         1000,
		AccentCooldownTicks: 5,
		AccentBaseProb:      1.0,
	})
	// Force into Flow so multiplier is non-zero.
	c.state.Section = SectionFlow

	lastFire := -100
	fires := 0
	for i := 0; i < 100; i++ {
		o := c.Tick(nil)
		if len(o.Accents) > 0 {
			if i-lastFire < 5 && fires > 0 {
				t.Fatalf("cooldown violated: fire at %d, last at %d (gap %d < 5)", i, lastFire, i-lastFire)
			}
			lastFire = i
			fires++
		}
	}
	if fires == 0 {
		t.Fatal("expected at least one accent over 100 ticks at prob=1")
	}
}

// TestDeterministicSeed: same seed + same input produces identical output.
func TestDeterministicSeed(t *testing.T) {
	a, _ := runFor(99, 100, genEvents(3, 50))
	b, _ := runFor(99, 100, genEvents(3, 50))
	if a != b {
		t.Fatalf("non-deterministic with fixed seed: a=%d b=%d", a, b)
	}
}
