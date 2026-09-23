package main

import "testing"

func TestParseStartClock(t *testing.T) {
	tests := []struct {
		spec string
		want int
	}{
		{"", 0},
		{"16:00", 16 * 3600},
		{"16:15:30", 16*3600 + 15*60 + 30},
	}

	for _, tt := range tests {
		got, err := parseStartClock(tt.spec)
		if err != nil {
			t.Fatalf("parseStartClock(%q): %v", tt.spec, err)
		}
		if got != tt.want {
			t.Fatalf("parseStartClock(%q) = %d, want %d", tt.spec, got, tt.want)
		}
	}
}

func TestParseStartClockRejectsInvalid(t *testing.T) {
	for _, spec := range []string{"24:00", "16", "aa:bb"} {
		if _, err := parseStartClock(spec); err == nil {
			t.Fatalf("parseStartClock(%q): expected error", spec)
		}
	}
}

func TestSourceWindowForRenderSecond(t *testing.T) {
	start, end := sourceWindowForRenderSecond(16*3600, 12, 0)
	if start != 16*3600 || end != 16*3600+12 {
		t.Fatalf("window 0 = [%d,%d), want [%d,%d)", start, end, 16*3600, 16*3600+12)
	}

	start, end = sourceWindowForRenderSecond(16*3600, 12, 299)
	if start != 16*3600+3588 || end != 17*3600 {
		t.Fatalf("window 299 = [%d,%d), want [%d,%d)", start, end, 16*3600+3588, 17*3600)
	}
}
