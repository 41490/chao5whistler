package main

import (
	"slices"
	"testing"
)

func TestParseHoursEmptyMeansWholeDay(t *testing.T) {
	hours, err := parseHours("")
	if err != nil {
		t.Fatalf("parseHours: %v", err)
	}
	if len(hours) != 24 {
		t.Fatalf("len(hours) = %d, want 24", len(hours))
	}
	if hours[0] != 0 || hours[23] != 23 {
		t.Fatalf("hours endpoints = %v, want 0..23", []int{hours[0], hours[23]})
	}
}

func TestParseHoursRangeAndDedup(t *testing.T) {
	hours, err := parseHours("16,12-14,13,0")
	if err != nil {
		t.Fatalf("parseHours: %v", err)
	}
	want := []int{0, 12, 13, 14, 16}
	if !slices.Equal(hours, want) {
		t.Fatalf("hours = %v, want %v", hours, want)
	}
}

func TestParseHoursRejectsInvalid(t *testing.T) {
	tests := []string{"-1", "24", "7-3", "a", "1,,2", "1-2-3"}
	for _, spec := range tests {
		if _, err := parseHours(spec); err == nil {
			t.Fatalf("parseHours(%q): expected error", spec)
		}
	}
}
