package video

import (
	"image/color"
	"testing"
)

func TestNewRenderer(t *testing.T) {
	r := New(1280, 720, 30, 180, 0.3, 0.9)
	if r.width != 1280 || r.height != 720 {
		t.Fatalf("expected 1280x720, got %dx%d", r.width, r.height)
	}
	if r.fps != 30 {
		t.Fatalf("expected fps 30, got %d", r.fps)
	}
}

func TestRenderEmptyFrame(t *testing.T) {
	r := New(1280, 720, 30, 180, 0.3, 0.9)
	img := r.RenderFrame()

	bounds := img.Bounds()
	if bounds.Dx() != 1280 || bounds.Dy() != 720 {
		t.Fatalf("expected 1280x720 image, got %dx%d", bounds.Dx(), bounds.Dy())
	}

	// Check background pixel at a central location.
	c := img.At(640, 360)
	rr, gg, bb, _ := c.RGBA()
	// RGBA() returns pre-multiplied 16-bit values; shift to 8-bit.
	r8, g8, b8 := uint8(rr>>8), uint8(gg>>8), uint8(bb>>8)

	// Solarized Dark: #002b36 -> R:0 G:43 B:54
	if r8 != 0 || g8 != 43 || b8 != 54 {
		t.Fatalf("expected bg R:0 G:43 B:54, got R:%d G:%d B:%d", r8, g8, b8)
	}
}

func TestSpawnAndDespawn(t *testing.T) {
	// speed=180 px/s, fps=30 -> 6 px/frame.
	// spawnYMax=0.9 -> max spawn ~648. 648/6 = 108 frames to reach y=0.
	// Use 150 frames for safety margin.
	r := New(1280, 720, 30, 180, 0.3, 0.9)
	r.SpawnText("hello", 128)

	if len(r.floaters) != 1 {
		t.Fatalf("expected 1 floater after spawn, got %d", len(r.floaters))
	}

	for i := 0; i < 150; i++ {
		r.RenderFrame()
	}

	if len(r.floaters) != 0 {
		t.Fatalf("expected 0 floaters after 150 frames, got %d", len(r.floaters))
	}
}

func TestParseHexColor(t *testing.T) {
	c := parseHex("#002b36")
	want := color.RGBA{R: 0, G: 43, B: 54, A: 255}
	if c != want {
		t.Fatalf("expected %v, got %v", want, c)
	}
}
