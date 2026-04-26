// live-v2: realtime audio-only ghsingo loop driven by the v2 backend
// abstraction (#34). Mirrors cmd/live's lifecycle (load config + daypack,
// pace at wall-clock, encode through ffmpeg) but knows nothing about
// bell-era mixer or cluster types — every sample comes from a backend.Backend.
//
// This binary is intentionally audio-only. Live video is gated on a
// separate composer-driven visual layer (#39).
//
// Usage:
//
//	go run ./cmd/live-v2 --config ghsingo-v2.toml --duration 5m
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"syscall"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
	"github.com/41490/chao5whistler/src/ghsingo/internal/audio"
	"github.com/41490/chao5whistler/src/ghsingo/internal/backend"
	"github.com/41490/chao5whistler/src/ghsingo/internal/backend/gov2"
	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
	"github.com/41490/chao5whistler/src/ghsingo/internal/lifecycle"
	"github.com/41490/chao5whistler/src/ghsingo/internal/replay"
)



func main() {
	configPath := flag.String("config", "ghsingo-v2.toml", "path to v2 config")
	durationStr := flag.String("duration", "0", "max duration (0 = until SIGINT)")
	outOverride := flag.String("o", "", "override output path; empty uses cfg.Output.Local.Path")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
		os.Exit(1)
	}
	if cfg.ResolvedEngine() != "v2" {
		slog.Error("live-v2 requires meta.engine = \"v2\"", "config", *configPath, "got", cfg.ResolvedEngine())
		os.Exit(2)
	}

	duration, err := time.ParseDuration(*durationStr)
	if err != nil {
		slog.Error("invalid duration", "err", err)
		os.Exit(1)
	}

	daypackPath, dateStr, err := findLatestDaypack(cfg.Archive.DaypackDir)
	if err != nil {
		slog.Error("find daypack", "err", err)
		os.Exit(1)
	}
	pack, err := archive.ReadDaypack(daypackPath)
	if err != nil {
		slog.Error("read daypack", "err", err)
		os.Exit(1)
	}
	slog.Info("live-v2 starting",
		"profile", cfg.Meta.Profile,
		"engine", cfg.ResolvedEngine(),
		"daypack_date", dateStr,
		"duration", duration,
	)

	box := lifecycle.NewBackendBox(
		func() (backend.Backend, error) { return buildBackend(cfg) },
		cfg.Audio.SampleRate/cfg.Video.FPS,
	)
	if err := box.Init(); err != nil {
		// #36 contract: do NOT exit. ffmpeg pipe must outlive backend
		// startup failures so the RTMP session never drops. Log + carry on
		// emitting silence; SIGUSR1 / scheduled timers can retry Init.
		slog.Warn("backend init failed; live stream proceeding with silence", "err", err)
	}
	defer box.Close()
	slog.Info("backend wrapper ready", "name", box.Name(), "sample_rate", box.SampleRate())

	outPath := *outOverride
	if outPath == "" {
		outPath = cfg.Output.Local.Path
		// Apply the {date} placeholder the bell-era live used.
		if outPath == "" {
			outPath = "/tmp/ghsingo-live-v2.flv"
		}
	}
	if err := os.MkdirAll(filepath.Dir(outPath), 0755); err != nil {
		slog.Error("mkdir", "err", err)
		os.Exit(1)
	}

	cmd := exec.Command("ffmpeg",
		"-f", "f32le",
		"-ar", fmt.Sprintf("%d", cfg.Audio.SampleRate),
		"-ac", "2",
		"-i", "pipe:0",
		"-c:a", "aac",
		"-b:a", "192k",
		"-y", outPath,
	)
	cmd.Stderr = os.Stderr
	stdin, err := cmd.StdinPipe()
	if err != nil {
		slog.Error("ffmpeg pipe", "err", err)
		os.Exit(1)
	}
	if err := cmd.Start(); err != nil {
		slog.Error("ffmpeg start", "err", err)
		os.Exit(1)
	}

	tickCh := make(chan replay.Tick, 16)
	engine := replay.New(pack, tickCh)
	startSec := replay.CurrentSecond()
	go engine.RunFrom(startSec, 0, time.Second) // wall-clock pacing

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	// #36: SIGUSR1 triggers a backend-only restart without dropping the
	// ffmpeg/RTMP pipe. Useful for ops to recover from a wedged scsynth
	// supervisor without bouncing the whole stream.
	restartCh := make(chan os.Signal, 1)
	signal.Notify(restartCh, syscall.SIGUSR1)
	go func() {
		for range restartCh {
			if err := box.Restart(); err != nil {
				slog.Warn("backend restart failed", "err", err)
			} else {
				slog.Info("backend restarted", "count", box.RestartCount())
			}
		}
	}()

	frameTicker := time.NewTicker(time.Second / time.Duration(cfg.Video.FPS))
	defer frameTicker.Stop()

	deadline := time.Time{}
	if duration > 0 {
		deadline = time.Now().Add(duration)
	}

	var currentTick replay.Tick
	lastSecond := -1
loop:
	for {
		select {
		case <-sigCh:
			slog.Info("shutting down on signal")
			break loop
		case t, ok := <-tickCh:
			if !ok {
				slog.Info("daypack exhausted")
				break loop
			}
			currentTick = t
		case <-frameTicker.C:
			if currentTick.Second != lastSecond {
				box.ApplyEventsForSecond(toBackendEvents(currentTick.Events))
				lastSecond = currentTick.Second
			}
			samples, err := box.RenderFrame()
			if err != nil {
				slog.Error("render", "err", err)
				break loop
			}
			if _, err := stdin.Write(pcmToBytes(samples)); err != nil {
				slog.Error("write", "err", err)
				break loop
			}
			if !deadline.IsZero() && time.Now().After(deadline) {
				slog.Info("duration reached")
				break loop
			}
		}
	}

	stdin.Close()
	if err := cmd.Wait(); err != nil {
		slog.Warn("ffmpeg wait", "err", err)
	}
	slog.Info("done",
		"output", outPath,
		"backend_restarts", box.RestartCount(),
		"last_init_err", box.LastInitErr(),
	)
}

func buildBackend(cfg *config.Config) (backend.Backend, error) {
	bankDir := cfg.Assets.Accents.BankDir
	bankDecay := cfg.Assets.Accents.SynthDecay
	var bank *audio.BellBank
	if bankDir != "" {
		bank = audio.NewBellBank(cfg.Audio.SampleRate)
		if bankDecay > 0 {
			bank.SetSynthDecay(bankDecay)
		}
		if _, err := bank.LoadFromDir(bankDir); err != nil {
			slog.Warn("load accent bank", "err", err, "path", bankDir)
		}
	}

	var tonalPCM []float32
	if cfg.Assets.TonalBed.WavPath != "" {
		pcm, err := audio.LoadWavFile(cfg.Assets.TonalBed.WavPath)
		if err != nil {
			slog.Warn("load tonal bed", "err", err, "path", cfg.Assets.TonalBed.WavPath)
		} else {
			tonalPCM = pcm
		}
	}

	return gov2.New(gov2.Options{
		SampleRate: cfg.Audio.SampleRate,
		FPS:        cfg.Video.FPS,
		Composer: composer.Config{
			EMAAlpha:             cfg.Composer.EMAAlpha,
			DensitySaturation:    cfg.Composer.DensitySaturation,
			BrightnessSaturation: cfg.Composer.BrightnessSaturation,
			PhraseTicks:          cfg.Composer.PhraseTicks,
			AccentCooldownTicks:  cfg.Composer.AccentCooldownTicks,
			AccentBaseProb:       cfg.Composer.AccentBaseProb,
			Seed:                 cfg.Composer.Seed,
		},
		Mixer: gov2.MixerConfig{
			MasterGain:    cfg.Mixer.MasterGain,
			DroneGain:     cfg.Mixer.DroneGain,
			BedGain:       cfg.Mixer.BedGain,
			TonalBedGain:  cfg.Mixer.TonalBedGain,
			AccentGain:    cfg.Mixer.AccentGain,
			WetContinuous: cfg.Mixer.WetContinuous,
			WetAccent:     cfg.Mixer.WetAccent,
			AccentMax:     cfg.Mixer.AccentMax,
		},
		Assets: gov2.AssetsConfig{
			TonalBedPCM:    tonalPCM,
			TonalBedGainDB: cfg.Assets.TonalBed.GainDB,
			AccentBank:     bank,
		},
	}), nil
}

func toBackendEvents(evs []archive.Event) []backend.Event {
	out := make([]backend.Event, len(evs))
	for i, e := range evs {
		out[i] = backend.Event{TypeID: e.TypeID, Weight: e.Weight}
	}
	return out
}

func pcmToBytes(samples []float32) []byte {
	buf := make([]byte, len(samples)*4)
	for i, s := range samples {
		binary.LittleEndian.PutUint32(buf[i*4:], math.Float32bits(s))
	}
	return buf
}

func findLatestDaypack(dir string) (string, string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return "", "", err
	}
	var dirs []string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		p := filepath.Join(dir, e.Name(), "day.bin")
		if _, serr := os.Stat(p); serr == nil {
			dirs = append(dirs, e.Name())
		}
	}
	if len(dirs) == 0 {
		return "", "", fmt.Errorf("no daypack in %q", dir)
	}
	sort.Strings(dirs)
	return filepath.Join(dir, dirs[len(dirs)-1], "day.bin"), dirs[len(dirs)-1], nil
}
