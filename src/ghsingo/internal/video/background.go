package video

import (
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"path/filepath"
	"sort"

	"github.com/fogleman/gg"
	xdraw "golang.org/x/image/draw"
)

type backgroundManifest struct {
	Frames []string `json:"frames"`
}

type BackgroundSequence struct {
	width        int
	height       int
	paths        []string
	switchFrames int
	fadeFrames   int
	currentIdx   int
	nextIdx      int
	currentImg   image.Image
	nextImg      image.Image
	frameCounter int
}

func LoadBackgroundSequence(dir string, width, height, switchFrames, fadeFrames int) (*BackgroundSequence, error) {
	paths, err := loadSequencePaths(dir)
	if err != nil {
		return nil, err
	}
	if len(paths) == 0 {
		return nil, fmt.Errorf("no background frames found in %q", dir)
	}
	if switchFrames <= 0 {
		switchFrames = 60
	}
	if fadeFrames < 0 {
		fadeFrames = 0
	}
	bg := &BackgroundSequence{
		width:        width,
		height:       height,
		paths:        paths,
		switchFrames: switchFrames,
		fadeFrames:   fadeFrames,
		currentIdx:   0,
		nextIdx:      nextSequenceIndex(0, len(paths)),
	}
	if bg.currentImg, err = decodeAndScaleImage(paths[0], width, height); err != nil {
		return nil, err
	}
	if len(paths) > 1 {
		if bg.nextImg, err = decodeAndScaleImage(paths[bg.nextIdx], width, height); err != nil {
			return nil, err
		}
	}
	return bg, nil
}

func (b *BackgroundSequence) Draw(dc *gg.Context) {
	if b == nil || b.currentImg == nil {
		return
	}
	drawImageFill(dc, b.currentImg)
	progress := 0.0
	if b.fadeFrames > 0 && b.frameCounter >= b.switchFrames-b.fadeFrames && b.nextImg != nil {
		progress = float64(b.frameCounter-(b.switchFrames-b.fadeFrames)) / float64(b.fadeFrames)
		if progress < 0 {
			progress = 0
		}
		if progress > 1 {
			progress = 1
		}
		drawImageFillAlpha(dc, b.nextImg, progress)
	}

	b.frameCounter++
	if b.frameCounter < b.switchFrames {
		return
	}
	b.frameCounter = 0
	b.currentIdx = b.nextIdx
	b.currentImg = b.nextImg
	b.nextIdx = nextSequenceIndex(b.currentIdx, len(b.paths))
	if len(b.paths) > 1 {
		if img, err := decodeAndScaleImage(b.paths[b.nextIdx], b.width, b.height); err == nil {
			b.nextImg = img
		}
	}
}

func (b *BackgroundSequence) DrawTo(dst draw.Image) {
	if b == nil || b.currentImg == nil || dst == nil {
		return
	}
	draw.Draw(dst, image.Rect(0, 0, b.width, b.height), b.currentImg, image.Point{}, draw.Src)
	if b.fadeFrames > 0 && b.frameCounter >= b.switchFrames-b.fadeFrames && b.nextImg != nil {
		progress := float64(b.frameCounter-(b.switchFrames-b.fadeFrames)) / float64(b.fadeFrames)
		if progress < 0 {
			progress = 0
		}
		if progress > 1 {
			progress = 1
		}
		alpha := uint8(progress * 255)
		if alpha > 0 {
			draw.DrawMask(
				dst,
				image.Rect(0, 0, b.width, b.height),
				b.nextImg,
				image.Point{},
				image.NewUniform(color.Alpha{A: alpha}),
				image.Point{},
				draw.Over,
			)
		}
	}

	b.frameCounter++
	if b.frameCounter < b.switchFrames {
		return
	}
	b.frameCounter = 0
	b.currentIdx = b.nextIdx
	b.currentImg = b.nextImg
	b.nextIdx = nextSequenceIndex(b.currentIdx, len(b.paths))
	if len(b.paths) > 1 {
		if img, err := decodeAndScaleImage(b.paths[b.nextIdx], b.width, b.height); err == nil {
			b.nextImg = img
		}
	}
}

func loadSequencePaths(dir string) ([]string, error) {
	manifestPath := filepath.Join(dir, "manifest.json")
	if data, err := os.ReadFile(manifestPath); err == nil {
		var manifest backgroundManifest
		if err := json.Unmarshal(data, &manifest); err != nil {
			return nil, fmt.Errorf("parse background manifest: %w", err)
		}
		paths := make([]string, 0, len(manifest.Frames))
		for _, name := range manifest.Frames {
			paths = append(paths, filepath.Join(dir, name))
		}
		return paths, nil
	}

	matches, err := filepath.Glob(filepath.Join(dir, "*.png"))
	if err != nil {
		return nil, fmt.Errorf("glob png sequence: %w", err)
	}
	sort.Strings(matches)
	return matches, nil
}

func decodeAndScaleImage(path string, width, height int) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open image %q: %w", path, err)
	}
	defer f.Close()
	img, _, err := image.Decode(f)
	if err != nil {
		return nil, fmt.Errorf("decode image %q: %w", path, err)
	}
	return scaleToFill(img, width, height), nil
}

func drawImageFill(dc *gg.Context, img image.Image) {
	drawImageFillAlpha(dc, img, 1.0)
}

func drawImageFillAlpha(dc *gg.Context, img image.Image, alpha float64) {
	if img == nil || alpha <= 0 {
		return
	}

	dc.Push()
	dc.SetRGBA(1, 1, 1, alpha)
	dc.DrawImageAnchored(img, 0, 0, 0, 0)
	dc.Pop()
}

func nextSequenceIndex(current, total int) int {
	if total <= 1 {
		return 0
	}
	return (current + 1) % total
}

func scaleToFill(src image.Image, width, height int) image.Image {
	if width <= 0 || height <= 0 {
		return src
	}
	srcBounds := src.Bounds()
	if srcBounds.Dx() == width && srcBounds.Dy() == height {
		return src
	}

	srcW := srcBounds.Dx()
	srcH := srcBounds.Dy()
	if srcW == 0 || srcH == 0 {
		return src
	}

	scaleX := float64(width) / float64(srcW)
	scaleY := float64(height) / float64(srcH)
	scale := scaleX
	if scaleY > scale {
		scale = scaleY
	}
	scaledW := int(float64(srcW) * scale)
	scaledH := int(float64(srcH) * scale)
	if scaledW < width {
		scaledW = width
	}
	if scaledH < height {
		scaledH = height
	}

	scaled := image.NewRGBA(image.Rect(0, 0, scaledW, scaledH))
	xdraw.BiLinear.Scale(scaled, scaled.Bounds(), src, srcBounds, xdraw.Over, nil)

	dst := image.NewRGBA(image.Rect(0, 0, width, height))
	offset := image.Point{
		X: (scaledW - width) / 2,
		Y: (scaledH - height) / 2,
	}
	draw.Draw(dst, dst.Bounds(), scaled, offset, draw.Src)
	return dst
}
