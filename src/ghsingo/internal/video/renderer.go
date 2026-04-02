package video

import (
	"image"
	"image/color"
	"image/draw"
	"math"
	"math/rand/v2"
	"strconv"

	"github.com/fogleman/gg"
	xdraw "golang.org/x/image/draw"
	"golang.org/x/image/font"
)

type floater struct {
	text            string
	x, y            float64
	fontSize        float64
	scale           float64
	alpha           float64
	speed           float64
	color           color.RGBA
	rotationRad     float64
	scaleGrowPerSec float64
	textExtent      float64
	ageSecs         float64
	wobbleAmp       float64
	wobbleFreq      float64
	wobblePhase     float64
	sprite          image.Image
	scaledSprites   map[int]image.Image
}

// Renderer draws rising/fading text floaters onto RGBA frames.
type Renderer struct {
	width, height   int
	fps             int
	speed           float64
	spawnYMin       float64
	spawnYMax       float64
	fontSizeMin     int
	fontSizeMax     int
	bgColor         color.RGBA
	textColor       color.RGBA
	accentColor     color.RGBA
	fontPath        string
	fontFaces       map[int]font.Face
	eventColors     map[uint8]color.RGBA
	bottomMargin    float64
	despawnYMin     float64
	despawnYMax     float64
	scaleGrowPerSec float64
	rotationRad     float64
	background      *BackgroundSequence
	canvas          *image.RGBA
	maxFloaters     int
	floaters        []*floater
}

// New creates a Renderer with the given dimensions and motion parameters.
func New(width, height, fps int, speed, spawnYMin, spawnYMax float64) *Renderer {
	return &Renderer{
		width:           width,
		height:          height,
		fps:             fps,
		speed:           speed,
		spawnYMin:       spawnYMin,
		spawnYMax:       spawnYMax,
		fontSizeMin:     14,
		fontSizeMax:     48,
		bgColor:         color.RGBA{R: 0, G: 43, B: 54, A: 255},
		textColor:       color.RGBA{R: 131, G: 148, B: 150, A: 255},
		accentColor:     color.RGBA{R: 38, G: 139, B: 210, A: 255},
		fontFaces:       map[int]font.Face{},
		eventColors:     map[uint8]color.RGBA{},
		bottomMargin:    16,
		despawnYMin:     0.18,
		despawnYMax:     0.45,
		scaleGrowPerSec: 0.22,
		rotationRad:     gg.Radians(90),
		canvas:          image.NewRGBA(image.Rect(0, 0, width, height)),
		maxFloaters:     24,
	}
}

// SetPalette overrides the default colour scheme. Each argument is a hex
// string like "#002b36".
func (r *Renderer) SetPalette(bg, text, accent string) {
	r.bgColor = ParseHex(bg)
	r.textColor = ParseHex(text)
	r.accentColor = ParseHex(accent)
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

func (r *Renderer) SetEventColors(colors map[uint8]color.RGBA) {
	r.eventColors = make(map[uint8]color.RGBA, len(colors))
	for k, v := range colors {
		r.eventColors[k] = v
	}
}

func (r *Renderer) SetTextMotion(bottomMargin int, despawnYMin, despawnYMax, scaleGrowPerSec, rotationDeg float64) {
	r.bottomMargin = float64(bottomMargin)
	r.despawnYMin = despawnYMin
	r.despawnYMax = despawnYMax
	r.scaleGrowPerSec = scaleGrowPerSec
	r.rotationRad = gg.Radians(rotationDeg)
}

func (r *Renderer) SetBackgroundSequence(bg *BackgroundSequence) {
	r.background = bg
}

// SpawnText adds a new text floater. weight (0-255) controls font size.
func (r *Renderer) SpawnText(text string, typeID uint8, weight uint8) {
	fontSize := float64(r.fontSizeMin) + float64(r.fontSizeMax-r.fontSizeMin)*float64(weight)/255.0
	xPad := fontSize * 0.75
	maxX := float64(r.width) - xPad
	if maxX < xPad {
		maxX = xPad
	}
	yBase := float64(r.height) - r.bottomMargin
	c := r.textColor
	if mapped, ok := r.eventColors[typeID]; ok {
		c = mapped
	}
	textExtent := r.measureTextExtent(text, fontSize)
	sprite := r.buildTextSprite(text, fontSize, c, r.rotationRad)

	r.floaters = append(r.floaters, &floater{
		text:            text,
		x:               xPad + rand.Float64()*(maxX-xPad),
		y:               yBase,
		fontSize:        fontSize,
		scale:           0.9,
		alpha:           220,
		speed:           r.speed,
		color:           c,
		rotationRad:     r.rotationRad,
		scaleGrowPerSec: r.scaleGrowPerSec,
		textExtent:      textExtent,
		wobbleAmp:       1 + rand.Float64()*3,
		wobbleFreq:      1.2 + rand.Float64()*1.8,
		wobblePhase:     rand.Float64() * math.Pi * 2,
		sprite:          sprite,
		scaledSprites:   map[int]image.Image{},
	})
	if r.maxFloaters > 0 && len(r.floaters) > r.maxFloaters {
		r.floaters = r.floaters[len(r.floaters)-r.maxFloaters:]
	}
}

// RenderFrame produces a single RGBA frame, advancing the simulation by one
// tick (1/fps seconds).
func (r *Renderer) RenderFrame() *image.RGBA {
	if r.canvas == nil {
		r.canvas = image.NewRGBA(image.Rect(0, 0, r.width, r.height))
	}
	draw.Draw(r.canvas, r.canvas.Bounds(), &image.Uniform{C: r.bgColor}, image.Point{}, draw.Src)
	if r.background != nil {
		r.background.DrawTo(r.canvas)
	}
	dc := gg.NewContextForRGBA(r.canvas)

	dt := 1.0 / float64(r.fps)
	span := (float64(r.height) - r.bottomMargin) - (r.despawnYMin * float64(r.height))
	if span <= 0 {
		span = float64(r.height)
	}

	for _, f := range r.floaters {
		f.y -= f.speed * dt
		f.ageSecs += dt
		f.scale += f.scaleGrowPerSec * dt
		halfExtent := (f.textExtent * f.scale) / 2
		if halfExtent < f.fontSize*0.5 {
			halfExtent = f.fontSize * 0.5
		}
		f.alpha = 220
		if f.y < halfExtent {
			progress := (halfExtent - f.y) / (halfExtent * 2)
			if progress < 0 {
				progress = 0
			}
			if progress > 1 {
				progress = 1
			}
			f.alpha = 220 * (1 - progress)
		}

		drawX := f.x + math.Sin(f.ageSecs*f.wobbleFreq*math.Pi*2+f.wobblePhase)*f.wobbleAmp
		if f.sprite != nil {
			dc.SetRGBA(1, 1, 1, f.alpha/255)
			dc.DrawImageAnchored(r.scaledSpriteFor(f), int(drawX), int(f.y), 0.5, 0.5)
		} else {
			dc.Push()
			dc.Translate(drawX, f.y)
			dc.Rotate(f.rotationRad)
			dc.Scale(f.scale, f.scale)
			if r.fontPath != "" {
				if face := r.fontFaceForSize(f.fontSize); face != nil {
					dc.SetFontFace(face)
				}
			}
			tc := color.NRGBA{R: f.color.R, G: f.color.G, B: f.color.B, A: uint8(f.alpha)}
			dc.SetColor(tc)
			dc.DrawStringAnchored(f.text, 0, 0, 0.5, 0.5)
			dc.Pop()
		}
	}

	alive := r.floaters[:0]
	for _, f := range r.floaters {
		halfExtent := (f.textExtent * f.scale) / 2
		if halfExtent < f.fontSize*0.5 {
			halfExtent = f.fontSize * 0.5
		}
		if f.y+halfExtent > 0 && f.alpha > 0 {
			alive = append(alive, f)
		}
	}
	r.floaters = alive

	return r.canvas
}

// RenderFrameRaw returns the raw RGBA pixel bytes suitable for piping to
// FFmpeg (rawvideo format).
func (r *Renderer) RenderFrameRaw() []byte {
	img := r.RenderFrame()
	return img.Pix
}

// ParseHex converts a hex colour string like "#002b36" to a color.RGBA.
func ParseHex(hex string) color.RGBA {
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

func (r *Renderer) fontFaceForSize(size float64) font.Face {
	if r.fontPath == "" {
		return nil
	}
	key := int(math.Round(size))
	if face, ok := r.fontFaces[key]; ok {
		return face
	}
	face, err := gg.LoadFontFace(r.fontPath, float64(key))
	if err != nil {
		return nil
	}
	r.fontFaces[key] = face
	return face
}

func (r *Renderer) measureTextExtent(text string, size float64) float64 {
	if r.fontPath != "" {
		if face := r.fontFaceForSize(size); face != nil {
			dc := gg.NewContext(1, 1)
			dc.SetFontFace(face)
			w, _ := dc.MeasureString(text)
			if w > 0 {
				return w
			}
		}
	}
	return math.Max(size, float64(len([]rune(text)))*size*0.6)
}

func (r *Renderer) buildTextSprite(text string, size float64, c color.RGBA, rotationRad float64) image.Image {
	if r.fontPath == "" {
		return nil
	}
	face := r.fontFaceForSize(size)
	if face == nil {
		return nil
	}
	measure := gg.NewContext(1, 1)
	measure.SetFontFace(face)
	w, h := measure.MeasureString(text)
	if w <= 0 {
		w = size
	}
	if h <= 0 {
		h = size
	}
	pad := math.Max(4, size*0.3)
	spriteW := int(math.Ceil(w + pad*2))
	spriteH := int(math.Ceil(h + pad*2))
	dc := gg.NewContext(spriteW, spriteH)
	dc.SetFontFace(face)
	dc.SetRGBA255(int(c.R), int(c.G), int(c.B), 255)
	dc.DrawStringAnchored(text, float64(spriteW)/2, float64(spriteH)/2, 0.5, 0.5)
	if math.Abs(rotationRad-gg.Radians(90)) < 0.001 {
		rot := gg.NewContext(spriteH, spriteW)
		rot.Translate(float64(spriteH)/2, float64(spriteW)/2)
		rot.Rotate(rotationRad)
		rot.DrawImageAnchored(dc.Image(), 0, 0, 0.5, 0.5)
		return rot.Image()
	}
	return dc.Image()
}

func (r *Renderer) scaledSpriteFor(f *floater) image.Image {
	if f == nil || f.sprite == nil {
		return nil
	}
	key := int(math.Round(f.scale * 20))
	if key < 1 {
		key = 1
	}
	if img, ok := f.scaledSprites[key]; ok {
		return img
	}
	scale := float64(key) / 20
	src := f.sprite.Bounds()
	w := int(math.Round(float64(src.Dx()) * scale))
	h := int(math.Round(float64(src.Dy()) * scale))
	if w < 1 {
		w = 1
	}
	if h < 1 {
		h = 1
	}
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	xdraw.NearestNeighbor.Scale(dst, dst.Bounds(), f.sprite, src, draw.Over, nil)
	f.scaledSprites[key] = dst
	return dst
}
