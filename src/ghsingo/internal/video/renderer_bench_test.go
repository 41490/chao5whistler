package video

import (
	"os"
	"testing"
)

// benchRenderer builds a renderer at the rsghsing target geometry (720p@30)
// with the shipped font and a full floater population, so the benchmarks
// measure a worst-case frame rather than an empty canvas.
//
// Issue #103 task 3b: ghsingo has no offline video path, so the frame
// generation cost that live-v2 cannot show is measured here. This file is
// add-only: no existing ghsingo file is touched.
func benchRenderer(b *testing.B) *Renderer {
	b.Helper()
	r := New(1280, 720, 30, 180, 0.3, 0.9)
	r.SetPalette("#002b36", "#fdf6e3", "#b58900")
	r.SetFontSizeRange(14, 42)
	r.SetTextMotion(16, 0.18, 0.45, 0.22, 90)
	// ../../../../ops/assets/ is relative to this package directory.
	const font = "../../../../ops/assets/3270NerdFontMono-Condensed.ttf"
	if _, err := os.Stat(font); err == nil {
		r.SetFontPath(font)
	} else {
		b.Logf("font %s unavailable; benchmarking without TTF text", font)
	}
	for i := 0; i < r.maxFloaters; i++ {
		r.SpawnText("PushEvent", 0, 128)
	}
	return r
}

// BenchmarkRenderFrame is the per-frame cost of the Go renderer, i.e. the
// frame-generation half of the 2x feasibility question (task 3b).
func BenchmarkRenderFrame(b *testing.B) {
	r := benchRenderer(b)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		r.RenderFrame()
	}
}

// BenchmarkRenderFrameRaw adds the byte slice that would be piped to ffmpeg.
func BenchmarkRenderFrameRaw(b *testing.B) {
	r := benchRenderer(b)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if len(r.RenderFrameRaw()) != 1280*720*4 {
			b.Fatal("unexpected frame size")
		}
	}
}
