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
	"strings"

	"github.com/fogleman/gg"
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

func LoadBackgroundSequence(configDir string, patterns []string, width, height, switchFrames, fadeFrames int) (*BackgroundSequence, error) {
	paths, err := loadSequencePaths(configDir, patterns)
	if err != nil {
		return nil, err
	}
	if len(paths) == 0 {
		return nil, fmt.Errorf("no background frames found after resolving %d background patterns", len(patterns))
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

func loadSequencePaths(configDir string, patterns []string) ([]string, error) {
	dirs, err := resolveSequenceDirs(configDir, patterns)
	if err != nil {
		return nil, err
	}
	paths := make([]string, 0)
	for _, dir := range dirs {
		seqPaths, err := loadSequenceDirPaths(dir)
		if err != nil {
			return nil, err
		}
		paths = append(paths, seqPaths...)
	}
	return paths, nil
}

func resolveSequenceDirs(configDir string, patterns []string) ([]string, error) {
	seen := map[string]struct{}{}
	var dirs []string
	for _, pattern := range patterns {
		pattern = strings.TrimSpace(pattern)
		if pattern == "" {
			continue
		}
		resolvedPattern := pattern
		if !filepath.IsAbs(resolvedPattern) {
			resolvedPattern = filepath.Join(configDir, resolvedPattern)
		}

		matches := []string{resolvedPattern}
		if hasGlobMeta(resolvedPattern) {
			var err error
			matches, err = filepath.Glob(resolvedPattern)
			if err != nil {
				return nil, fmt.Errorf("glob background sequence dirs %q: %w", pattern, err)
			}
			if len(matches) == 0 {
				return nil, fmt.Errorf("background sequence pattern %q matched no directories", pattern)
			}
			sort.Strings(matches)
		}

		for _, match := range matches {
			info, err := os.Stat(match)
			if err != nil {
				return nil, fmt.Errorf("stat background sequence dir %q: %w", match, err)
			}
			if !info.IsDir() {
				return nil, fmt.Errorf("background sequence path %q is not a directory", match)
			}
			cleaned := filepath.Clean(match)
			if _, ok := seen[cleaned]; ok {
				continue
			}
			seen[cleaned] = struct{}{}
			dirs = append(dirs, cleaned)
		}
	}
	if len(dirs) == 0 {
		return nil, fmt.Errorf("no background sequence directories configured")
	}
	return dirs, nil
}

func loadSequenceDirPaths(dir string) ([]string, error) {
	manifestPath := filepath.Join(dir, "manifest.json")
	if data, err := os.ReadFile(manifestPath); err == nil {
		var manifest backgroundManifest
		if err := json.Unmarshal(data, &manifest); err != nil {
			return nil, fmt.Errorf("parse background manifest: %w", err)
		}
		paths := make([]string, 0, len(manifest.Frames))
		for _, name := range manifest.Frames {
			path := filepath.Join(dir, name)
			if _, err := os.Stat(path); err != nil {
				return nil, fmt.Errorf("background manifest frame %q: %w", path, err)
			}
			paths = append(paths, path)
		}
		if len(paths) == 0 {
			return nil, fmt.Errorf("no background frames found in %q", dir)
		}
		return paths, nil
	}

	matches, err := filepath.Glob(filepath.Join(dir, "*.png"))
	if err != nil {
		return nil, fmt.Errorf("glob png sequence: %w", err)
	}
	sort.Strings(matches)
	if len(matches) == 0 {
		return nil, fmt.Errorf("no background frames found in %q", dir)
	}
	return matches, nil
}

func hasGlobMeta(path string) bool {
	return strings.ContainsAny(path, "*?[")
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
	return ScaleToFill(img, width, height), nil
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
