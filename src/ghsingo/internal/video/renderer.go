package video

import (
	"image"
	"image/color"
	"math/rand/v2"
	"strconv"

	"github.com/fogleman/gg"
)

type floater struct {
	text     string
	x, y     float64
	fontSize float64
	alpha    float64
	speed    float64
}

// Renderer draws rising/fading text floaters onto RGBA frames.
type Renderer struct {
	width, height int
	fps           int
	speed         float64 // pixels per second
	spawnYMin     float64 // fraction of height
	spawnYMax     float64
	fontSizeMin   int
	fontSizeMax   int
	bgColor       color.RGBA
	textColor     color.RGBA
	accentColor   color.RGBA
	fontPath      string
	floaters      []*floater
}

// New creates a Renderer with the given dimensions and motion parameters.
func New(width, height, fps int, speed, spawnYMin, spawnYMax float64) *Renderer {
	return &Renderer{
		width:       width,
		height:      height,
		fps:         fps,
		speed:       speed,
		spawnYMin:   spawnYMin,
		spawnYMax:   spawnYMax,
		fontSizeMin: 14,
		fontSizeMax: 48,
		bgColor:     color.RGBA{R: 0, G: 43, B: 54, A: 255},   // Solarized Dark
		textColor:   color.RGBA{R: 131, G: 148, B: 150, A: 255}, // Solarized base0
		accentColor: color.RGBA{R: 38, G: 139, B: 210, A: 255},  // Solarized blue
	}
}

// SetPalette overrides the default colour scheme. Each argument is a hex
// string like "#002b36".
func (r *Renderer) SetPalette(bg, text, accent string) {
	r.bgColor = parseHex(bg)
	r.textColor = parseHex(text)
	r.accentColor = parseHex(accent)
}

// SetFontSizeRange sets the minimum and maximum font sizes for spawned text.
func (r *Renderer) SetFontSizeRange(min, max int) {
	r.fontSizeMin = min
	r.fontSizeMax = max
}

// SetFontPath sets the path to a TrueType font file used for rendering.
func (r *Renderer) SetFontPath(path string) {
	r.fontPath = path
}

// SpawnText adds a new text floater. weight (0-255) controls font size.
func (r *Renderer) SpawnText(text string, weight uint8) {
	yMin := r.spawnYMin * float64(r.height)
	yMax := r.spawnYMax * float64(r.height)

	fontSize := float64(r.fontSizeMin) + float64(r.fontSizeMax-r.fontSizeMin)*float64(weight)/255.0

	f := &floater{
		text:     text,
		x:        rand.Float64() * float64(r.width),
		y:        yMin + rand.Float64()*(yMax-yMin),
		fontSize: fontSize,
		alpha:    220,
		speed:    r.speed,
	}
	r.floaters = append(r.floaters, f)
}

// RenderFrame produces a single RGBA frame, advancing the simulation by one
// tick (1/fps seconds).
func (r *Renderer) RenderFrame() *image.RGBA {
	dc := gg.NewContext(r.width, r.height)

	// Fill background.
	dc.SetColor(r.bgColor)
	dc.Clear()

	dt := 1.0 / float64(r.fps)
	ceilY := r.spawnYMax * float64(r.height)

	// Update and draw each floater.
	for _, f := range r.floaters {
		f.y -= f.speed * dt

		// Alpha fades as the floater rises toward the top.
		if ceilY > 0 {
			f.alpha = 220 * (f.y / ceilY)
		}
		if f.alpha < 0 {
			f.alpha = 0
		}

		if r.fontPath != "" {
			_ = dc.LoadFontFace(r.fontPath, f.fontSize)
		}

		a := uint8(f.alpha)
		tc := color.NRGBA{R: r.textColor.R, G: r.textColor.G, B: r.textColor.B, A: a}
		dc.SetColor(tc)
		dc.DrawStringAnchored(f.text, f.x, f.y, 0.5, 0.5)
	}

	// Cull despawned floaters.
	alive := r.floaters[:0]
	for _, f := range r.floaters {
		if f.y >= 0 && f.alpha > 0 {
			alive = append(alive, f)
		}
	}
	r.floaters = alive

	return dc.Image().(*image.RGBA)
}

// RenderFrameRaw returns the raw RGBA pixel bytes suitable for piping to
// FFmpeg (rawvideo format).
func (r *Renderer) RenderFrameRaw() []byte {
	img := r.RenderFrame()
	return img.Pix
}

// parseHex converts a hex colour string like "#002b36" to a color.RGBA.
func parseHex(hex string) color.RGBA {
	if len(hex) > 0 && hex[0] == '#' {
		hex = hex[1:]
	}
	if len(hex) != 6 {
		return color.RGBA{A: 255}
	}
	rv, _ := strconv.ParseUint(hex[0:2], 16, 8)
	gv, _ := strconv.ParseUint(hex[2:4], 16, 8)
	bv, _ := strconv.ParseUint(hex[4:6], 16, 8)
	return color.RGBA{R: uint8(rv), G: uint8(gv), B: uint8(bv), A: 255}
}
