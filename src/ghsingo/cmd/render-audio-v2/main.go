// render-audio-v2: Drive the v1 composer (#30) into the v2 ambient mixer
// (#31) and render an audio file. Same sidecar JSON contract as
// cmd/render-audio so audio-metrics can compare v2 directly against the
// frozen bell-era baseline (#29).
//
// Usage:
//
//	go run ./cmd/render-audio-v2 --config ghsingo.toml --duration 30s -o /tmp/v2.m4a
package main

import (
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
	"github.com/41490/chao5whistler/src/ghsingo/internal/audio"
	"github.com/41490/chao5whistler/src/ghsingo/internal/backend"
	"github.com/41490/chao5whistler/src/ghsingo/internal/backend/gov2"
	"github.com/41490/chao5whistler/src/ghsingo/internal/backend/sc"
	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
)

type sidecar struct {
	Profile             string  `json:"profile"`
	Engine              string  `json:"engine"`
	Legacy              bool    `json:"legacy"`
	Config              string  `json:"config"`
	DaypackDate         string  `json:"daypack_date"`
	DurationSecs        float64 `json:"duration_secs"`
	SampleRate          int     `json:"sample_rate"`
	Ticks               int     `json:"ticks"`
	LeadStrikes         int     `json:"lead_strikes"`
	BackgroundStrikes   int     `json:"background_strikes"`
	ReleaseAccents      int     `json:"release_accents"`
	EffStrikeRatePerSec float64 `json:"effective_strike_rate_per_sec"`
	ReleaseAccentRate   float64 `json:"release_accent_rate_per_sec"`
	FinalDensity        float64 `json:"final_density"`
	FinalBrightness     float64 `json:"final_brightness"`
	SectionTransitions  int     `json:"section_transitions"`
	ModeTransitions     int     `json:"mode_transitions"`
}

func main() {
	configPath := flag.String("config", "ghsingo.toml", "path to config file")
	outputPath := flag.String("o", "/tmp/ghsingo-audio-v2.m4a", "output audio path")
	durationStr := flag.String("duration", "30s", "render duration")
	seed := flag.Int64("seed", 0, "composer seed (0 = time.Now)")
	backendName := flag.String("backend", "go-v2", `audio backend: "go-v2" | "scsynth"`)
	synthDefDir := flag.String("synthdef-dir", "scsynth/synthdefs", "scsynth: where compiled .scsyndef files live")
	flag.Parse()

	dur, err := time.ParseDuration(*durationStr)
	if err != nil {
		slog.Error("invalid duration", "err", err)
		os.Exit(1)
	}
	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
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

	var be backend.Backend
	switch *backendName {
	case "go-v2", "":
		gob, err := buildGoV2Backend(cfg, *seed)
		if err != nil {
			slog.Error("build backend", "err", err)
			os.Exit(1)
		}
		be = gob
	case "scsynth":
		scb, err := sc.New(sc.Options{
			SampleRate:  cfg.Audio.SampleRate,
			FPS:         cfg.Video.FPS,
			Composer:    composerConfigFrom(cfg, *seed),
			SynthDefDir: *synthDefDir,
		})
		if err != nil {
			slog.Error("build scsynth backend", "err", err)
			os.Exit(1)
		}
		be = scb
	default:
		slog.Error("unknown --backend", "got", *backendName, "want", "go-v2|scsynth")
		os.Exit(2)
	}
	if err := be.Init(); err != nil {
		slog.Error("backend init", "err", err)
		os.Exit(1)
	}
	defer be.Close()

	if err := os.MkdirAll(filepath.Dir(*outputPath), 0755); err != nil {
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
		"-y", *outputPath,
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

	totalFrames := int(dur.Seconds() * float64(cfg.Video.FPS))
	framesPerSec := cfg.Video.FPS
	side := sidecar{
		Profile:     cfg.Meta.Profile,
		Engine:      be.Name(),
		Legacy:      cfg.Meta.Legacy,
		Config:      *configPath,
		DaypackDate: dateStr,
		SampleRate:  cfg.Audio.SampleRate,
	}

	tick := -1
	for f := 0; f < totalFrames; f++ {
		secOfRender := f / framesPerSec
		if secOfRender != tick {
			tick = secOfRender
			idx := tick % len(pack.Ticks)
			evs := pack.Ticks[idx].Events
			be.ApplyEventsForSecond(toBackendEvents(evs))
		}

		samples, err := be.RenderFrame()
		if err != nil {
			slog.Error("render", "err", err)
			break
		}
		buf := pcmToBytes(samples)
		if _, err := stdin.Write(buf); err != nil {
			slog.Error("write", "err", err)
			break
		}

		if (f+1)%framesPerSec == 0 && (f+1)%(framesPerSec*5) == 0 {
			slog.Info("v2 progress", "rendered", time.Duration(f+1)*time.Second/time.Duration(framesPerSec), "target", dur)
		}
	}

	stdin.Close()
	if err := cmd.Wait(); err != nil {
		slog.Error("ffmpeg wait", "err", err)
		os.Exit(1)
	}

	switch impl := be.(type) {
	case *gov2.Backend:
		s := impl.Stats()
		side.Ticks = s.Ticks
		side.LeadStrikes = s.Accents
		side.SectionTransitions = s.SectionTransitions
		side.ModeTransitions = s.ModeTransitions
		side.FinalDensity = impl.LastState().Density
		side.FinalBrightness = impl.LastState().Brightness
	case *sc.Backend:
		side.LeadStrikes = int(impl.AccentsFired())
		side.FinalDensity = impl.LastState().Density
		side.FinalBrightness = impl.LastState().Brightness
	}
	side.DurationSecs = float64(totalFrames) / float64(framesPerSec)
	if side.DurationSecs > 0 {
		side.EffStrikeRatePerSec = float64(side.LeadStrikes) / side.DurationSecs
		side.ReleaseAccentRate = float64(side.ReleaseAccents) / side.DurationSecs
	}

	sidePath := *outputPath + ".metrics.json"
	if err := writeSidecar(sidePath, side); err != nil {
		slog.Warn("sidecar", "err", err)
	} else {
		slog.Info("metrics sidecar", "path", sidePath)
	}
	slog.Info("done v2",
		"output", *outputPath,
		"ticks", side.Ticks,
		"accents", side.LeadStrikes,
		"final_density", fmt.Sprintf("%.3f", side.FinalDensity),
		"final_brightness", fmt.Sprintf("%.3f", side.FinalBrightness),
	)
}

// composerConfigFrom maps a v2-shaped Config to composer.Config,
// applying an optional CLI seed override. Shared by gov2 + sc backends.
func composerConfigFrom(cfg *config.Config, seedOverride int64) composer.Config {
	out := composer.Config{
		EMAAlpha:             cfg.Composer.EMAAlpha,
		DensitySaturation:    cfg.Composer.DensitySaturation,
		BrightnessSaturation: cfg.Composer.BrightnessSaturation,
		PhraseTicks:          cfg.Composer.PhraseTicks,
		AccentCooldownTicks:  cfg.Composer.AccentCooldownTicks,
		AccentBaseProb:       cfg.Composer.AccentBaseProb,
		Seed:                 cfg.Composer.Seed,
	}
	if seedOverride != 0 {
		out.Seed = seedOverride
	}
	return out
}

// buildGoV2Backend assembles the gov2 backend from a v2-shaped config
// and an optional CLI seed override. It performs the I/O the backend
// itself refuses to do (loading WAV samples, the bell bank).
func buildGoV2Backend(cfg *config.Config, seedOverride int64) (*gov2.Backend, error) {
	composerCfg := composerConfigFrom(cfg, seedOverride)

	mixerCfg := gov2.MixerConfig{
		MasterGain:    cfg.Mixer.MasterGain,
		DroneGain:     cfg.Mixer.DroneGain,
		BedGain:       cfg.Mixer.BedGain,
		TonalBedGain:  cfg.Mixer.TonalBedGain,
		AccentGain:    cfg.Mixer.AccentGain,
		WetContinuous: cfg.Mixer.WetContinuous,
		WetAccent:     cfg.Mixer.WetAccent,
		AccentMax:     cfg.Mixer.AccentMax,
	}

	assets := gov2.AssetsConfig{}

	// Accent bank: prefer v2 [assets.accents]; fall back to legacy
	// [audio.bells] only when the v2 block is absent (migration aid).
	bankDir := cfg.Assets.Accents.BankDir
	bankDecay := cfg.Assets.Accents.SynthDecay
	if bankDir == "" {
		bankDir = cfg.Audio.Bells.BankDir
		bankDecay = cfg.Audio.Bells.SynthDecay
	}
	if bankDir != "" {
		bank := audio.NewBellBank(cfg.Audio.SampleRate)
		if bankDecay > 0 {
			bank.SetSynthDecay(bankDecay)
		}
		if _, err := bank.LoadFromDir(bankDir); err != nil {
			slog.Warn("load accent bank", "err", err, "path", bankDir)
		}
		assets.AccentBank = bank
		assets.AccentSynthDecay = bankDecay
	}

	// Tonal bed: prefer v2 [assets.tonal_bed]; fall back to legacy
	// [audio.bgm] only when the v2 block is absent (migration aid).
	tbPath := cfg.Assets.TonalBed.WavPath
	tbGainDB := cfg.Assets.TonalBed.GainDB
	if tbPath == "" {
		tbPath = cfg.Audio.BGM.WavPath
		tbGainDB = cfg.Audio.BGM.GainDB
	}
	if tbPath != "" {
		pcm, err := audio.LoadWavFile(tbPath)
		if err != nil {
			slog.Warn("load tonal bed", "err", err, "path", tbPath)
		} else {
			assets.TonalBedPCM = pcm
			assets.TonalBedGainDB = tbGainDB
			slog.Info("tonal bed loaded", "samples", len(pcm), "path", tbPath)
		}
	}

	return gov2.New(gov2.Options{
		SampleRate: cfg.Audio.SampleRate,
		FPS:        cfg.Video.FPS,
		Composer:   composerCfg,
		Mixer:      mixerCfg,
		Assets:     assets,
	}), nil
}

func toBackendEvents(evs []archive.Event) []backend.Event {
	out := make([]backend.Event, len(evs))
	for i, e := range evs {
		out[i] = backend.Event{TypeID: e.TypeID, Weight: e.Weight}
	}
	return out
}

func writeSidecar(path string, m sidecar) error {
	buf, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(buf, '\n'), 0644)
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
	latest := dirs[len(dirs)-1]
	return filepath.Join(dir, latest, "day.bin"), latest, nil
}
