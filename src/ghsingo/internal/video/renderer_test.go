package video

import (
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"os"
	"path/filepath"
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

	c := img.At(640, 360)
	rr, gg, bb, _ := c.RGBA()
	r8, g8, b8 := uint8(rr>>8), uint8(gg>>8), uint8(bb>>8)
	if r8 != 0 || g8 != 43 || b8 != 54 {
		t.Fatalf("expected bg R:0 G:43 B:54, got R:%d G:%d B:%d", r8, g8, b8)
	}
}

func TestSpawnAndDespawn(t *testing.T) {
	r := New(1280, 720, 30, 180, 0.3, 0.9)
	r.SetTextMotion(16, 0.18, 0.18, 0.22, 90)
	r.SpawnText("hello", 0, 128)

	if len(r.floaters) != 1 {
		t.Fatalf("expected 1 floater after spawn, got %d", len(r.floaters))
	}
	f := r.floaters[0]
	if f.y != 704 {
		t.Fatalf("expected floater baseline y=704, got %.1f", f.y)
	}
	if f.rotationRad == 0 {
		t.Fatal("expected rotated floater")
	}
	if f.textExtent <= 0 {
		t.Fatal("expected measured text extent")
	}
	if f.wobbleAmp < 1 || f.wobbleAmp > 4 {
		t.Fatalf("expected wobble amp in [2,14], got %.2f", f.wobbleAmp)
	}

	for i := 0; i < 260; i++ {
		r.RenderFrame()
	}

	if len(r.floaters) != 0 {
		t.Fatalf("expected 0 floaters after render loop, got %d", len(r.floaters))
	}
}

func TestParseHexColor(t *testing.T) {
	c := ParseHex("#002b36")
	want := color.RGBA{R: 0, G: 43, B: 54, A: 255}
	if c != want {
		t.Fatalf("expected %v, got %v", want, c)
	}
}

func TestEventColorMapping(t *testing.T) {
	r := New(1280, 720, 30, 180, 0.3, 0.9)
	r.SetEventColors(map[uint8]color.RGBA{
		2: {R: 0xcb, G: 0x4b, B: 0x16, A: 255},
	})
	r.SpawnText("issue", 2, 128)
	if got := r.floaters[0].color; got.R != 0xcb || got.G != 0x4b || got.B != 0x16 {
		t.Fatalf("expected mapped event color, got %+v", got)
	}
}

func TestFloaterLivesUntilAboveTop(t *testing.T) {
	r := New(1280, 720, 30, 180, 0.3, 0.9)
	r.SetTextMotion(16, 0.18, 0.18, 0.22, 90)
	r.SpawnText("vertical", 0, 200)

	for i := 0; i < 110; i++ {
		r.RenderFrame()
	}
	if len(r.floaters) != 1 {
		t.Fatalf("expected floater still alive before leaving top edge, got %d", len(r.floaters))
	}
}

func TestBackgroundSequenceLoadsManifest(t *testing.T) {
	dir := t.TempDir()
	writeSolidPNG(t, filepath.Join(dir, "0001.png"), color.RGBA{R: 10, G: 20, B: 30, A: 255})
	writeSolidPNG(t, filepath.Join(dir, "0002.png"), color.RGBA{R: 40, G: 50, B: 60, A: 255})
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), []byte(`{"frames":["0001.png","0002.png"]}`), 0644); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	bg, err := LoadBackgroundSequence("", []string{dir}, 64, 64, 60, 6)
	if err != nil {
		t.Fatalf("LoadBackgroundSequence() error: %v", err)
	}
	if len(bg.paths) != 2 {
		t.Fatalf("expected 2 background paths, got %d", len(bg.paths))
	}
}

func TestLoadBackgroundSequenceExpandsGlobAndDedupesDirs(t *testing.T) {
	root := t.TempDir()
	dir1 := filepath.Join(root, "ScavengersReign01")
	dir2 := filepath.Join(root, "ScavengersReign02")
	if err := os.MkdirAll(dir1, 0755); err != nil {
		t.Fatalf("mkdir dir1: %v", err)
	}
	if err := os.MkdirAll(dir2, 0755); err != nil {
		t.Fatalf("mkdir dir2: %v", err)
	}
	writeSolidPNG(t, filepath.Join(dir1, "0002.png"), color.RGBA{R: 20, A: 255})
	writeSolidPNG(t, filepath.Join(dir1, "0001.png"), color.RGBA{R: 10, A: 255})
	writeSolidPNG(t, filepath.Join(dir2, "0001.png"), color.RGBA{R: 30, A: 255})

	bg, err := LoadBackgroundSequence("", []string{
		filepath.Join(root, "ScavengersReign0*"),
		dir1,
	}, 64, 64, 1, 0)
	if err != nil {
		t.Fatalf("LoadBackgroundSequence() error: %v", err)
	}
	if len(bg.paths) != 3 {
		t.Fatalf("expected 3 background paths, got %d", len(bg.paths))
	}
	if got := filepath.Base(filepath.Dir(bg.paths[0])); got != "ScavengersReign01" {
		t.Fatalf("first path dir = %q, want ScavengersReign01", got)
	}
	if got := filepath.Base(bg.paths[0]); got != "0001.png" {
		t.Fatalf("first path base = %q, want 0001.png", got)
	}
	if got := filepath.Base(filepath.Dir(bg.paths[2])); got != "ScavengersReign02" {
		t.Fatalf("last path dir = %q, want ScavengersReign02", got)
	}
}

func TestLoadBackgroundSequenceFailsOnZeroMatch(t *testing.T) {
	_, err := LoadBackgroundSequence("", []string{"/no/such/dir/*"}, 64, 64, 60, 0)
	if err == nil {
		t.Fatal("expected zero-match error, got nil")
	}
}

func TestBackgroundSequenceWrapsAcrossDirectories(t *testing.T) {
	root := t.TempDir()
	dir1 := filepath.Join(root, "A")
	dir2 := filepath.Join(root, "B")
	if err := os.MkdirAll(dir1, 0755); err != nil {
		t.Fatalf("mkdir dir1: %v", err)
	}
	if err := os.MkdirAll(dir2, 0755); err != nil {
		t.Fatalf("mkdir dir2: %v", err)
	}
	writeSolidPNG(t, filepath.Join(dir1, "0001.png"), color.RGBA{R: 10, A: 255})
	writeSolidPNG(t, filepath.Join(dir2, "0001.png"), color.RGBA{R: 20, A: 255})

	bg, err := LoadBackgroundSequence("", []string{dir1, dir2}, 8, 8, 1, 0)
	if err != nil {
		t.Fatalf("LoadBackgroundSequence() error: %v", err)
	}

	dst := image.NewRGBA(image.Rect(0, 0, 8, 8))
	bg.DrawTo(dst)
	if got := rgbaAt(dst, 0, 0).R; got != 10 {
		t.Fatalf("frame 1 R = %d, want 10", got)
	}

	draw.Draw(dst, dst.Bounds(), image.Transparent, image.Point{}, draw.Src)
	bg.DrawTo(dst)
	if got := rgbaAt(dst, 0, 0).R; got != 20 {
		t.Fatalf("frame 2 R = %d, want 20", got)
	}

	draw.Draw(dst, dst.Bounds(), image.Transparent, image.Point{}, draw.Src)
	bg.DrawTo(dst)
	if got := rgbaAt(dst, 0, 0).R; got != 10 {
		t.Fatalf("frame 3 R = %d, want wrap to 10", got)
	}
}

func rgbaAt(img *image.RGBA, x, y int) color.RGBA {
	return img.RGBAAt(x, y)
}

func writeSolidPNG(t *testing.T, path string, c color.RGBA) {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, 8, 8))
	for y := 0; y < 8; y++ {
		for x := 0; x < 8; x++ {
			img.SetRGBA(x, y, c)
		}
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create png: %v", err)
	}
	defer f.Close()
	if err := png.Encode(f, img); err != nil {
		t.Fatalf("encode png: %v", err)
	}
}
