package main

import "testing"

const sampleStderr = `[Parsed_loudnorm_0 @ 0x55]
{
	"input_i" : "-23.50",
	"input_tp" : "-1.10",
	"input_lra" : "8.20",
	"input_thresh" : "-33.55",
	"output_i" : "-16.04",
	"output_tp" : "-1.50",
	"output_lra" : "7.40",
	"output_thresh" : "-26.06",
	"normalization_type" : "dynamic",
	"target_offset" : "0.04"
}
`

func TestParseLoudnorm(t *testing.T) {
	got, err := parseLoudnorm([]byte(sampleStderr))
	if err != nil {
		t.Fatalf("parseLoudnorm: %v", err)
	}
	if got.IntegratedLUFS != -23.5 {
		t.Errorf("integrated: got %v want -23.5", got.IntegratedLUFS)
	}
	if got.TruePeakDBTP != -1.10 {
		t.Errorf("true peak: got %v want -1.10", got.TruePeakDBTP)
	}
	if got.LRA != 8.20 {
		t.Errorf("lra: got %v want 8.20", got.LRA)
	}
	if got.ThresholdLUFS != -33.55 {
		t.Errorf("thresh: got %v want -33.55", got.ThresholdLUFS)
	}
}

func TestParseLoudnormMissing(t *testing.T) {
	if _, err := parseLoudnorm([]byte("ffmpeg ran but produced no JSON")); err == nil {
		t.Fatal("expected error on missing JSON")
	}
}
