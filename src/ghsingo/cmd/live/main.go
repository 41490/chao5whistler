package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"image/color"
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

	// --- 3. Create audio mixer: BGM + beat + bell bank + Release ocean ---
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

	mixer.SetBeat(audio.GainToLinear(cfg.Audio.Beat.GainDB))
	slog.Info("beat enabled", "gain_db", cfg.Audio.Beat.GainDB)

	bank := audio.NewBellBank(cfg.Audio.SampleRate)
	if cfg.Audio.Bells.SynthDecay > 0 {
		bank.SetSynthDecay(cfg.Audio.Bells.SynthDecay)
	}
	if cfg.Audio.Bells.BankDir != "" {
		loaded, err := bank.LoadFromDir(cfg.Audio.Bells.BankDir)
		if err != nil {
			slog.Error("load bell bank", "err", err)
			os.Exit(1)
		}
		slog.Info("bell bank loaded", "dir", cfg.Audio.Bells.BankDir, "samples", loaded)
	}
	mixer.SetBellBank(bank,
		audio.GainToLinear(cfg.Audio.Bells.SampleGainDB),
		audio.GainToLinear(cfg.Audio.Bells.SynthGainDB),
	)

	// Optional: load ReleaseEvent ocean sample for big-moment layering.
	if rel, ok := cfg.Audio.Voices["ReleaseEvent"]; ok && rel.WavPath != "" {
		pcm, err := audio.LoadWavFile(rel.WavPath)
		if err != nil {
			slog.Warn("load release ocean", "err", err)
		} else {
			mixer.SetReleaseOcean(pcm, audio.GainToLinear(rel.GainDB))
			slog.Info("release ocean loaded", "samples", len(pcm))
		}
	}

	clusterCfg := buildClusterConfig(cfg.Audio.Cluster)

	// --- 4. Create video renderer ---
	renderer := video.New(
		cfg.Video.Width, cfg.Video.Height, cfg.Video.FPS,
		cfg.Video.Motion.SpeedPxPerSec,
		cfg.Video.Motion.SpawnYMin,
		cfg.Video.Motion.SpawnYMax,
	)
	renderer.SetPalette(cfg.Video.Palette.Background, cfg.Video.Palette.Text, cfg.Video.Palette.Accent)
	renderer.SetFontSizeRange(cfg.Video.FontSizeMin, cfg.Video.FontSizeMax)
	renderer.SetTextMotion(
		cfg.Video.Text.BottomMarginPx,
		cfg.Video.Text.DespawnYMin,
		cfg.Video.Text.DespawnYMax,
		cfg.Video.Text.ScaleGrowPerSec,
		cfg.Video.Text.RotationDeg,
	)
	renderer.SetEventColors(resolveEventColors(cfg.Video.EventColors))
	if cfg.Video.FontPath != "" {
		renderer.SetFontPath(cfg.Video.FontPath)
	}
	if cfg.Video.Background.Mode == "mosaic_sequence" {
		switchFrames := int(cfg.Video.Background.SwitchEverySecs * float64(cfg.Video.FPS))
		fadeSecs := cfg.Video.Background.FadeSecs
		if fadeSecs > cfg.Video.Background.SwitchEverySecs {
			fadeSecs = cfg.Video.Background.SwitchEverySecs
		}
		fadeFrames := int(fadeSecs * float64(cfg.Video.FPS))
		bg, err := video.LoadBackgroundSequence(
			filepath.Dir(*configPath),
			cfg.Video.Background.Patterns(),
			cfg.Video.Width,
			cfg.Video.Height,
			switchFrames,
			fadeFrames,
		)
		if err != nil {
			slog.Error("load background sequence", "err", err)
			os.Exit(1)
		}
		renderer.SetBackgroundSequence(bg)
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
		VideoBitrateKbps: cfg.Output.VideoBitrateKbps,
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
		currentTick replay.Tick
		lastSecond  = -1
		frameCount  uint64
		startTime   = time.Now()
		audioBuf    []byte
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
				renderer.SpawnText(ev.Text, ev.TypeID, ev.Weight)
			}

		case <-frameTicker.C:
			// If this is the first frame of a new second, run the cluster
			// assigner over the second's events and schedule the resulting
			// note triggers (BellBank handles staggering / decay overlap).
			if currentTick.Second != lastSecond {
				entries := make([]audio.EventEntry, len(currentTick.Events))
				for i, ev := range currentTick.Events {
					entries[i] = audio.EventEntry{TypeID: ev.TypeID, Weight: ev.Weight}
				}
				triggers := audio.Assign(entries, clusterCfg)
				mixer.ScheduleNotes(triggers)
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
			audioBuf = pcmToBytes(audioSamples, audioBuf)
			if err := mgr.WriteAudio(audioBuf); err != nil {
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
func pcmToBytes(samples []float32, reuse []byte) []byte {
	if cap(reuse) < len(samples)*4 {
		reuse = make([]byte, len(samples)*4)
	}
	buf := reuse[:len(samples)*4]
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

func resolveEventColors(raw map[string]string) map[uint8]color.RGBA {
	out := make(map[uint8]color.RGBA, len(raw))
	for name, hex := range raw {
		typeID, ok := config.EventTypeID[name]
		if !ok {
			continue
		}
		out[typeID] = video.ParseHex(hex)
	}
	return out
}

// buildClusterConfig converts config.AudioCluster into audio.ClusterConfig,
// resolving event-type names to uint8 IDs via config.EventTypeID.
func buildClusterConfig(c config.AudioCluster) audio.ClusterConfig {
	resolve := func(names []string) []uint8 {
		out := make([]uint8, 0, len(names))
		for _, n := range names {
			if id, ok := config.EventTypeID[n]; ok {
				out = append(out, id)
			}
		}
		return out
	}
	toOctave := func(n int) audio.Octave {
		switch n {
		case 3:
			return audio.OctaveLow
		case 4:
			return audio.OctaveMid
		case 5:
			return audio.OctaveHigh
		}
		return audio.OctaveMid
	}
	octaveList := func(ns []int) []audio.Octave {
		out := make([]audio.Octave, len(ns))
		for i, n := range ns {
			out[i] = toOctave(n)
		}
		return out
	}
	return audio.ClusterConfig{
		KeepTopN:        c.KeepTopN,
		EventTypeIDs:    resolve(c.EventTypes),
		AlwaysFireIDs:   resolve(c.AlwaysFire),
		Velocities:      c.Velocities,
		ReleaseVelocity: c.ReleaseVelocity,
		OctaveRank1:     toOctave(c.OctaveRank1),
		OctaveRank2:     octaveList(c.OctaveRank2),
		OctaveRank3:     toOctave(c.OctaveRank3),
		OctaveRank4:     toOctave(c.OctaveRank4),
		OctaveRelease:   toOctave(c.OctaveRelease),
		SpreadMs:        c.SpreadMs,
	}
}
