package audio

import "testing"

func TestBeatDensityMapping(t *testing.T) {
	b := NewBeatGenerator(44100, 1.0)

	cases := []struct {
		events int
		want   float64
	}{
		{events: 0, want: 60},
		{events: 4, want: 60},
		{events: 5, want: 72},
		{events: 19, want: 72},
		{events: 20, want: 90},
		{events: 49, want: 90},
		{events: 50, want: 120},
	}

	for _, tc := range cases {
		b.SetDensity(tc.events)
		if got := b.TargetBPM(); got != tc.want {
			t.Fatalf("events=%d target=%v want=%v", tc.events, got, tc.want)
		}
	}
}

func TestBeatBPMTransitionIsSmooth(t *testing.T) {
	b := NewBeatGenerator(44100, 1.0)
	start := b.CurrentBPM()

	b.SetDensity(60)
	afterOne := b.NextSample()
	if afterOne == 0 {
		t.Log("first sample may be zero before the first kick, checking BPM only")
	}

	afterOneBPM := b.CurrentBPM()
	if !(afterOneBPM > start && afterOneBPM < 120.0) {
		t.Fatalf("first BPM step=%f want between %f and 120", afterOneBPM, start)
	}

	for i := 0; i < 44100; i++ {
		b.NextSample()
	}
	afterOneSecond := b.CurrentBPM()
	if !(afterOneSecond > afterOneBPM && afterOneSecond < 120.0) {
		t.Fatalf("after 1s BPM=%f want increased but not snapped to 120", afterOneSecond)
	}
}

func TestBeatProducesKickPulse(t *testing.T) {
	b := NewBeatGenerator(44100, 1.0)

	var max float32
	for i := 0; i < 44100; i++ {
		s := b.NextSample()
		if s < 0 {
			s = -s
		}
		if s > max {
			max = s
		}
	}

	if max <= 0.01 {
		t.Fatalf("max beat amplitude=%f want audible non-zero kick", max)
	}
}
