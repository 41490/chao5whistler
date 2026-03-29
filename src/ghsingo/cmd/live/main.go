package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
	"github.com/41490/chao5whistler/src/ghsingo/internal/audio"
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
	"github.com/41490/chao5whistler/src/ghsingo/internal/replay"
	"github.com/41490/chao5whistler/src/ghsingo/internal/stream"
	"github.com/41490/chao5whistler/src/ghsingo/internal/video"
)

func main() {
	configPath := flag.String("config", "ghsingo.toml", "path to config file")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
		os.Exit(1)
	}

	slog.Info("live starting", "profile", cfg.Meta.Profile)

	// --- 1. Find latest daypack ---
	daypackPath, dateStr, err := findLatestDaypack(cfg.Archive.DaypackDir)
	if err != nil {
		slog.Error("find daypack", "err", err)
		os.Exit(1)
	}
	slog.Info("using daypack", "path", daypackPath, "date", dateStr)

	// --- 2. Read daypack ---
	pack, err := archive.ReadDaypack(daypackPath)
	if err != nil {
		slog.Error("read daypack", "err", err)
		os.Exit(1)
	}
	slog.Info("daypack loaded", "ticks", pack.Header.TotalTicks, "date", pack.Header.Date)

	// --- 3. Create audio mixer, load BGM + voices ---
	mixer := audio.NewMixer(cfg.Audio.SampleRate, cfg.Video.FPS)

	if cfg.Audio.BGM.WavPath != "" {
		bgmPCM, err := audio.LoadWavFile(cfg.Audio.BGM.WavPath)
		if err != nil {
			slog.Error("load bgm", "err", err)
			os.Exit(1)
		}
		mixer.SetBGM(bgmPCM, audio.GainToLinear(cfg.Audio.BGM.GainDB))
		slog.Info("bgm loaded", "path", cfg.Audio.BGM.WavPath, "samples", len(bgmPCM))
	}

	for name, voice := range cfg.Audio.Voices {
		typeID, ok := config.EventTypeID[name]
		if !ok {
			slog.Warn("unknown voice event type, skipping", "name", name)
			continue
		}
		pcm, err := audio.LoadWavFile(voice.WavPath)
		if err != nil {
			slog.Error("load voice", "name", name, "err", err)
			os.Exit(1)
		}
		mixer.RegisterVoice(typeID, pcm, audio.GainToLinear(voice.GainDB))
		slog.Info("voice loaded", "name", name, "type_id", typeID, "samples", len(pcm))
	}

	// --- 4. Create video renderer ---
	renderer := video.New(
		cfg.Video.Width, cfg.Video.Height, cfg.Video.FPS,
		cfg.Video.Motion.SpeedPxPerSec,
		cfg.Video.Motion.SpawnYMin,
		cfg.Video.Motion.SpawnYMax,
	)
	renderer.SetPalette(cfg.Video.Palette.Background, cfg.Video.Palette.Text, cfg.Video.Palette.Accent)
	renderer.SetFontSizeRange(cfg.Video.FontSizeMin, cfg.Video.FontSizeMax)
	if cfg.Video.FontPath != "" {
		renderer.SetFontPath(cfg.Video.FontPath)
	}

	// --- 5. Create stream manager ---
	outputPath := cfg.Output.Local.Path
	if strings.Contains(outputPath, "{date}") {
		outputPath = strings.ReplaceAll(outputPath, "{date}", dateStr)
	}
	if cfg.Output.Mode == "local" && outputPath != "" {
		if err := os.MkdirAll(filepath.Dir(outputPath), 0755); err != nil {
			slog.Error("create output dir", "err", err)
			os.Exit(1)
		}
	}

	mgr := stream.NewManager(stream.Options{
		Width:            cfg.Video.Width,
		Height:           cfg.Video.Height,
		FPS:              cfg.Video.FPS,
		VideoPreset:      cfg.Output.VideoPreset,
		AudioBitrateKbps: cfg.Output.AudioBitrateKbps,
		SampleRate:       cfg.Audio.SampleRate,
		Mode:             cfg.Output.Mode,
		OutputPath:       outputPath,
		RTMPSURL:         cfg.Output.RTMPS.URL,
	})

	// --- 6. Start FFmpeg ---
	if err := mgr.Start(); err != nil {
		slog.Error("start ffmpeg", "err", err)
		os.Exit(1)
	}
	defer func() {
		if err := mgr.Stop(); err != nil {
			slog.Error("stop ffmpeg", "err", err)
		}
	}()

	// --- 7. Start replay engine ---
	tickCh := make(chan replay.Tick, 16)
	engine := replay.New(pack, tickCh)
	startSec := replay.CurrentSecond()
	slog.Info("replay starting", "start_second", startSec)

	go engine.RunFrom(startSec, 0, time.Second)

	// --- 8. Main loop ---
	frameTicker := time.NewTicker(time.Second / time.Duration(cfg.Video.FPS))
	defer frameTicker.Stop()

	statsInterval := cfg.Observe.EmitStatsEverySecs
	if statsInterval <= 0 {
		statsInterval = 30
	}
	statsTicker := time.NewTicker(time.Duration(statsInterval) * time.Second)
	defer statsTicker.Stop()

	var (
		currentTick  replay.Tick
		lastSecond   = -1
		frameCount   uint64
		startTime    = time.Now()
	)

	for {
		select {
		case t, ok := <-tickCh:
			if !ok {
				slog.Info("tick channel closed, shutting down")
				return
			}
			currentTick = t
			// Spawn text floaters for new events immediately.
			for _, ev := range currentTick.Events {
				renderer.SpawnText(ev.Text, ev.Weight)
			}

		case <-frameTicker.C:
			// If this is the first frame of a new second, trigger audio events.
			if currentTick.Second != lastSecond {
				for _, ev := range currentTick.Events {
					mixer.TriggerEvent(ev.TypeID, ev.Weight)
				}
				lastSecond = currentTick.Second
			}

			// Render video frame.
			videoData := renderer.RenderFrameRaw()
			if err := mgr.WriteVideo(videoData); err != nil {
				slog.Error("write video", "err", err)
				return
			}

			// Render audio frame.
			audioSamples := mixer.RenderFrame(nil)
			audioBytes := pcmToBytes(audioSamples)
			if err := mgr.WriteAudio(audioBytes); err != nil {
				slog.Error("write audio", "err", err)
				return
			}

			frameCount++

		case <-statsTicker.C:
			uptime := time.Since(startTime).Truncate(time.Second)
			slog.Info("stats",
				"frames", frameCount,
				"current_second", currentTick.Second,
				"uptime", uptime.String(),
				"fps_avg", fmt.Sprintf("%.1f", float64(frameCount)/math.Max(time.Since(startTime).Seconds(), 1)),
			)
		}
	}
}

// pcmToBytes converts interleaved float32 PCM samples to little-endian f32le
// bytes suitable for FFmpeg's f32le audio input format.
func pcmToBytes(samples []float32) []byte {
	buf := make([]byte, len(samples)*4)
	for i, s := range samples {
		binary.LittleEndian.PutUint32(buf[i*4:], math.Float32bits(s))
	}
	return buf
}

// findLatestDaypack scans daypackDir for date-named subdirectories, sorts them,
// and returns the path to day.bin in the most recent one.
func findLatestDaypack(daypackDir string) (binPath, dateStr string, err error) {
	entries, err := os.ReadDir(daypackDir)
	if err != nil {
		return "", "", fmt.Errorf("read daypack dir %q: %w", daypackDir, err)
	}

	var dirs []string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		// Expect date-like names (e.g. "2026-03-28").
		name := e.Name()
		p := filepath.Join(daypackDir, name, "day.bin")
		if _, serr := os.Stat(p); serr == nil {
			dirs = append(dirs, name)
		}
	}

	if len(dirs) == 0 {
		return "", "", fmt.Errorf("no daypack directories with day.bin found in %q", daypackDir)
	}

	sort.Strings(dirs)
	latest := dirs[len(dirs)-1]
	return filepath.Join(daypackDir, latest, "day.bin"), latest, nil
}
