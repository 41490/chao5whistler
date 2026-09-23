package main

import (
	"encoding/json"
	"image"
	"strings"
	"testing"
)

func TestParseResolution(t *testing.T) {
	width, height, err := parseResolution("1280x720")
	if err != nil {
		t.Fatalf("parseResolution() error = %v", err)
	}
	if width != 1280 || height != 720 {
		t.Fatalf("parseResolution() = (%d, %d), want (1280, 720)", width, height)
	}
}

func TestParseResolutionEmptyUsesSourceSize(t *testing.T) {
	width, height, err := resolveOutputSize("", 1920, 1080)
	if err != nil {
		t.Fatalf("resolveOutputSize() error = %v", err)
	}
	if width != 1920 || height != 1080 {
		t.Fatalf("resolveOutputSize() = (%d, %d), want (1920, 1080)", width, height)
	}
}

func TestParseResolutionRejectsInvalidFormat(t *testing.T) {
	_, _, err := parseResolution("1280")
	if err == nil {
		t.Fatal("expected error for invalid resolution format, got nil")
	}
	if !strings.Contains(err.Error(), "WIDTHxHEIGHT") {
		t.Fatalf("error %q should mention WIDTHxHEIGHT", err.Error())
	}
}

func TestParseResolutionRejectsTrailingGarbage(t *testing.T) {
	_, _, err := parseResolution("1280x720foo")
	if err == nil {
		t.Fatal("expected error for trailing garbage, got nil")
	}
	if !strings.Contains(err.Error(), "height") {
		t.Fatalf("error %q should mention height", err.Error())
	}
}

func TestResizeOutputReturnsRequestedSize(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 1920, 1080))
	resized := resizeOutput(src, 1280, 720)
	if got := resized.Bounds().Dx(); got != 1280 {
		t.Fatalf("resized width = %d, want 1280", got)
	}
	if got := resized.Bounds().Dy(); got != 720 {
		t.Fatalf("resized height = %d, want 720", got)
	}
}

func TestManifestIncludesSourceAndOutputSize(t *testing.T) {
	m := manifest{
		VideoPath:    "demo.mp4",
		SourceWidth:  1920,
		SourceHeight: 1080,
		OutputWidth:  1280,
		OutputHeight: 720,
		Frames:       []string{"frame-0001.png"},
	}
	data, err := json.Marshal(m)
	if err != nil {
		t.Fatalf("json.Marshal() error = %v", err)
	}
	text := string(data)
	for _, needle := range []string{
		`"source_width":1920`,
		`"source_height":1080`,
		`"output_width":1280`,
		`"output_height":720`,
	} {
		if !strings.Contains(text, needle) {
			t.Fatalf("manifest json %q missing %s", text, needle)
		}
	}
}
