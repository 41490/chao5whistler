package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/BurntSushi/toml"
)

type Config struct {
	Input struct {
		VideoPath string `toml:"video_path"`
	} `toml:"input"`
	Output struct {
		Dir       string `toml:"dir"`
		PNGPrefix string `toml:"png_prefix"`
	} `toml:"output"`
	Sampling struct {
		WindowSecs float64 `toml:"window_secs"`
		MaxFrames  int     `toml:"max_frames"`
	} `toml:"sampling"`
	Effect struct {
		GridWidthPx     int     `toml:"grid_width_px"`
		GridHeightPx    int     `toml:"grid_height_px"`
		GlowStrength    float64 `toml:"glow_strength"`
		GlowWidthPx     int     `toml:"glow_width_px"`
		BlurRadiusPx    int     `toml:"blur_radius_px"`
		BrightnessScale float64 `toml:"brightness_scale"`
	} `toml:"effect"`
	Observe struct {
		LogLevel string `toml:"log_level"`
	} `toml:"observe"`
}

type ffprobeFormat struct {
	Duration string `json:"duration"`
}

type ffprobeStream struct {
	Width  int `json:"width"`
	Height int `json:"height"`
}

type ffprobeOutput struct {
	Streams []ffprobeStream `json:"streams"`
	Format  ffprobeFormat   `json:"format"`
}

type manifest struct {
	VideoPath       string   `json:"video_path"`
	GeneratedAt     string   `json:"generated_at"`
	WindowSecs      float64  `json:"window_secs"`
	GridWidthPx     int      `json:"grid_width_px"`
	GridHeightPx    int      `json:"grid_height_px"`
	GlowStrength    float64  `json:"glow_strength"`
	BlurRadiusPx    int      `json:"blur_radius_px"`
	BrightnessScale float64  `json:"brightness_scale"`
	Frames          []string `json:"frames"`
}

func main() {
	configPath := flag.String("config", "movpixer.toml", "path to movpixer config")
	flag.Parse()

	cfg, err := loadConfig(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
		os.Exit(1)
	}
	if err := os.MkdirAll(cfg.Output.Dir, 0755); err != nil {
		slog.Error("create output dir", "err", err)
		os.Exit(1)
	}

	duration, width, height, err := probeVideo(cfg.Input.VideoPath)
	if err != nil {
		slog.Error("probe video", "err", err)
		os.Exit(1)
	}
	window := cfg.Sampling.WindowSecs
	if window <= 0 {
		window = 2.0
	}
	frameCount := int(math.Ceil(duration / window))
	if cfg.Sampling.MaxFrames > 0 && cfg.Sampling.MaxFrames < frameCount {
		frameCount = cfg.Sampling.MaxFrames
	}

	slog.Info("movpixer starting",
		"video", cfg.Input.VideoPath,
		"duration_secs", fmt.Sprintf("%.2f", duration),
		"frames", frameCount,
		"size", fmt.Sprintf("%dx%d", width, height),
	)

	m := manifest{
		VideoPath:       cfg.Input.VideoPath,
		GeneratedAt:     time.Now().Format(time.RFC3339),
		WindowSecs:      window,
		GridWidthPx:     cfg.Effect.GridWidthPx,
		GridHeightPx:    cfg.Effect.GridHeightPx,
		GlowStrength:    cfg.Effect.GlowStrength,
		BlurRadiusPx:    cfg.Effect.BlurRadiusPx,
		BrightnessScale: cfg.Effect.BrightnessScale,
		Frames:          make([]string, 0, frameCount),
	}

	for i := 0; i < frameCount; i++ {
		start := float64(i) * window
		ts := math.Min(duration-0.05, start+window*0.5)
		if ts < 0 {
			ts = 0
		}

		frame, err := extractFrame(cfg.Input.VideoPath, ts)
		if err != nil {
			slog.Error("extract frame", "index", i, "ts", fmt.Sprintf("%.2f", ts), "err", err)
			os.Exit(1)
		}
		out := pixelate(
			frame,
			cfg.Effect.GridWidthPx,
			cfg.Effect.GridHeightPx,
			cfg.Effect.GlowWidthPx,
			cfg.Effect.GlowStrength,
			cfg.Effect.BlurRadiusPx,
			cfg.Effect.BrightnessScale,
		)
		name := fmt.Sprintf("%s-%04d.png", cfg.Output.PNGPrefix, i+1)
		outPath := filepath.Join(cfg.Output.Dir, name)
		if err := writePNG(outPath, out); err != nil {
			slog.Error("write png", "path", outPath, "err", err)
			os.Exit(1)
		}
		m.Frames = append(m.Frames, name)
	}

	manifestPath := filepath.Join(cfg.Output.Dir, "manifest.json")
	if err := writeManifest(manifestPath, m); err != nil {
		slog.Error("write manifest", "err", err)
		os.Exit(1)
	}
	slog.Info("movpixer done", "output_dir", cfg.Output.Dir, "frames", len(m.Frames))
}

func loadConfig(path string) (*Config, error) {
	var cfg Config
	if _, err := toml.DecodeFile(path, &cfg); err != nil {
		return nil, fmt.Errorf("decode %s: %w", path, err)
	}
	if cfg.Output.PNGPrefix == "" {
		cfg.Output.PNGPrefix = "frame"
	}
	if cfg.Effect.GridWidthPx <= 0 {
		cfg.Effect.GridWidthPx = 72
	}
	if cfg.Effect.GridHeightPx <= 0 {
		cfg.Effect.GridHeightPx = 72
	}
	if cfg.Effect.GlowWidthPx <= 0 {
		cfg.Effect.GlowWidthPx = 12
	}
	if cfg.Effect.GlowWidthPx > 24 {
		cfg.Effect.GlowWidthPx = 24
	}
	if cfg.Effect.GlowStrength <= 0 {
		cfg.Effect.GlowStrength = 0.20
	}
	if cfg.Effect.BlurRadiusPx < 0 {
		cfg.Effect.BlurRadiusPx = 0
	}
	if cfg.Effect.BlurRadiusPx == 0 {
		cfg.Effect.BlurRadiusPx = 4
	}
	if cfg.Effect.BrightnessScale <= 0 {
		cfg.Effect.BrightnessScale = 0.68
	}
	return &cfg, nil
}

func probeVideo(path string) (duration float64, width int, height int, err error) {
	out, err := exec.Command("ffprobe",
		"-v", "error",
		"-select_streams", "v:0",
		"-show_entries", "stream=width,height:format=duration",
		"-of", "json",
		path,
	).Output()
	if err != nil {
		return 0, 0, 0, fmt.Errorf("ffprobe %s: %w", path, err)
	}
	var parsed ffprobeOutput
	if err := json.Unmarshal(out, &parsed); err != nil {
		return 0, 0, 0, fmt.Errorf("parse ffprobe json: %w", err)
	}
	if len(parsed.Streams) == 0 {
		return 0, 0, 0, fmt.Errorf("ffprobe returned no video streams")
	}
	if _, err := fmt.Sscanf(parsed.Format.Duration, "%f", &duration); err != nil {
		return 0, 0, 0, fmt.Errorf("parse duration %q: %w", parsed.Format.Duration, err)
	}
	return duration, parsed.Streams[0].Width, parsed.Streams[0].Height, nil
}

func extractFrame(videoPath string, ts float64) (image.Image, error) {
	cmd := exec.Command("ffmpeg",
		"-v", "error",
		"-ss", fmt.Sprintf("%.3f", ts),
		"-i", videoPath,
		"-frames:v", "1",
		"-f", "image2pipe",
		"-vcodec", "png",
		"pipe:1",
	)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("ffmpeg extract frame at %.3fs: %w: %s", ts, err, stderr.String())
	}
	img, err := png.Decode(bytes.NewReader(stdout.Bytes()))
	if err != nil {
		return nil, fmt.Errorf("decode extracted png: %w", err)
	}
	return img, nil
}

func pixelate(src image.Image, gridW, gridH, glowWidth int, glowStrength float64, blurRadius int, brightnessScale float64) image.Image {
	b := src.Bounds()
	dst := image.NewRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
	draw.Draw(dst, dst.Bounds(), &image.Uniform{C: color.RGBA{R: 0, G: 18, B: 24, A: 255}}, image.Point{}, draw.Src)

	if glowWidth < 1 {
		glowWidth = 1
	}
	if glowWidth > 8 {
		glowWidth = 8
	}
	for y := 0; y < b.Dy(); y += gridH {
		for x := 0; x < b.Dx(); x += gridW {
			cell := image.Rect(x, y, minInt(x+gridW, b.Dx()), minInt(y+gridH, b.Dy()))
			avg := averageColor(src, cell)
			drawCellInnerGlow(dst, cell, avg, glowWidth, glowStrength)
		}
	}
	if blurRadius > 0 {
		dst = gaussianBlurApprox(dst, blurRadius)
	}
	if brightnessScale != 1 {
		applyBrightness(dst, brightnessScale)
	}
	return dst
}

func averageColor(img image.Image, rect image.Rectangle) color.RGBA {
	var rSum, gSum, bSum, count uint64
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		for x := rect.Min.X; x < rect.Max.X; x++ {
			r, g, b, _ := img.At(x+img.Bounds().Min.X, y+img.Bounds().Min.Y).RGBA()
			rSum += uint64(r >> 8)
			gSum += uint64(g >> 8)
			bSum += uint64(b >> 8)
			count++
		}
	}
	if count == 0 {
		return color.RGBA{}
	}
	return color.RGBA{
		R: uint8(rSum / count),
		G: uint8(gSum / count),
		B: uint8(bSum / count),
		A: 255,
	}
}

func drawCellInnerGlow(dst *image.RGBA, rect image.Rectangle, base color.RGBA, width int, glowStrength float64) {
	if rect.Dx() <= 0 || rect.Dy() <= 0 {
		return
	}
	if width < 1 {
		width = 1
	}
	glow := lighten(base, glowStrength)
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		for x := rect.Min.X; x < rect.Max.X; x++ {
			edgeDist := minInt(
				minInt(x-rect.Min.X, rect.Max.X-1-x),
				minInt(y-rect.Min.Y, rect.Max.Y-1-y),
			)
			mix := 0.0
			if edgeDist < width {
				mix = float64(width-edgeDist) / float64(width)
			}
			dst.SetRGBA(x, y, mixColor(base, glow, mix))
		}
	}
}

func lighten(c color.RGBA, strength float64) color.RGBA {
	apply := func(v uint8) uint8 {
		fv := float64(v)
		out := fv + (255-fv)*strength
		if out > 255 {
			out = 255
		}
		return uint8(out)
	}
	return color.RGBA{R: apply(c.R), G: apply(c.G), B: apply(c.B), A: 255}
}

func mixColor(base, glow color.RGBA, ratio float64) color.RGBA {
	if ratio <= 0 {
		return base
	}
	if ratio > 1 {
		ratio = 1
	}
	blend := func(a, b uint8) uint8 {
		return uint8(math.Round(float64(a)*(1-ratio) + float64(b)*ratio))
	}
	return color.RGBA{
		R: blend(base.R, glow.R),
		G: blend(base.G, glow.G),
		B: blend(base.B, glow.B),
		A: 255,
	}
}

func applyBrightness(img *image.RGBA, scale float64) {
	if scale < 0 {
		scale = 0
	}
	for i := 0; i < len(img.Pix); i += 4 {
		img.Pix[i] = scaleByte(img.Pix[i], scale)
		img.Pix[i+1] = scaleByte(img.Pix[i+1], scale)
		img.Pix[i+2] = scaleByte(img.Pix[i+2], scale)
	}
}

func scaleByte(v uint8, scale float64) uint8 {
	out := math.Round(float64(v) * scale)
	if out < 0 {
		out = 0
	}
	if out > 255 {
		out = 255
	}
	return uint8(out)
}

func gaussianBlurApprox(src *image.RGBA, radius int) *image.RGBA {
	if radius <= 0 {
		return src
	}
	tmp := boxBlur(src, radius)
	tmp = boxBlur(tmp, radius)
	return boxBlur(tmp, radius)
}

func boxBlur(src *image.RGBA, radius int) *image.RGBA {
	if radius <= 0 {
		return src
	}
	horizontal := image.NewRGBA(src.Bounds())
	vertical := image.NewRGBA(src.Bounds())

	for y := src.Bounds().Min.Y; y < src.Bounds().Max.Y; y++ {
		for x := src.Bounds().Min.X; x < src.Bounds().Max.X; x++ {
			var rSum, gSum, bSum, aSum, count int
			for xx := maxInt(src.Bounds().Min.X, x-radius); xx <= minInt(src.Bounds().Max.X-1, x+radius); xx++ {
				off := src.PixOffset(xx, y)
				rSum += int(src.Pix[off])
				gSum += int(src.Pix[off+1])
				bSum += int(src.Pix[off+2])
				aSum += int(src.Pix[off+3])
				count++
			}
			off := horizontal.PixOffset(x, y)
			horizontal.Pix[off] = uint8(rSum / count)
			horizontal.Pix[off+1] = uint8(gSum / count)
			horizontal.Pix[off+2] = uint8(bSum / count)
			horizontal.Pix[off+3] = uint8(aSum / count)
		}
	}

	for y := src.Bounds().Min.Y; y < src.Bounds().Max.Y; y++ {
		for x := src.Bounds().Min.X; x < src.Bounds().Max.X; x++ {
			var rSum, gSum, bSum, aSum, count int
			for yy := maxInt(src.Bounds().Min.Y, y-radius); yy <= minInt(src.Bounds().Max.Y-1, y+radius); yy++ {
				off := horizontal.PixOffset(x, yy)
				rSum += int(horizontal.Pix[off])
				gSum += int(horizontal.Pix[off+1])
				bSum += int(horizontal.Pix[off+2])
				aSum += int(horizontal.Pix[off+3])
				count++
			}
			off := vertical.PixOffset(x, y)
			vertical.Pix[off] = uint8(rSum / count)
			vertical.Pix[off+1] = uint8(gSum / count)
			vertical.Pix[off+2] = uint8(bSum / count)
			vertical.Pix[off+3] = uint8(aSum / count)
		}
	}
	return vertical
}

func writePNG(path string, img image.Image) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, img)
}

func writeManifest(path string, m manifest) error {
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0644)
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
