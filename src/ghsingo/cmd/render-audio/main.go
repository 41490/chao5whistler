// render-audio: Generate a standalone MP3 audio file from a ghsingo daypack.
// Runs the full audio pipeline (BGM + synthesized beat + event voices) without any video
// rendering or streaming. Use this to quickly verify musicality changes.
//
// Usage:
//
//	go run ./cmd/render-audio --config ghsingo.toml --duration 5m -o /tmp/out.mp3
//	ffplay /tmp/out.mp3
package main

import (
	"encoding/binary"
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
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
	"github.com/41490/chao5whistler/src/ghsingo/internal/replay"
)

func main() {
	configPath := flag.String("config", "ghsingo.toml", "path to config file")
	outputPath := flag.String("o", "/tmp/ghsingo-audio.m4a", "output M4A path")
	durationStr := flag.String("duration", "5m", "render duration (e.g. 30s, 5m, 1h)")
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

	slog.Info("render-audio starting",
		"duration", dur,
		"output", *outputPath,
		"sample_rate", cfg.Audio.SampleRate,
	)

	// --- Load daypack ---
	daypackPath, dateStr, err := findLatestDaypack(cfg.Archive.DaypackDir)
	if err != nil {
		slog.Error("find daypack", "err", err)
		os.Exit(1)
	}
	slog.Info("using daypack", "path", daypackPath, "date", dateStr)

	pack, err := archive.ReadDaypack(daypackPath)
	if err != nil {
		slog.Error("read daypack", "err", err)
		os.Exit(1)
	}

	// --- Build mixer: BGM + beat + bell bank + Release ocean ---
	mixer := audio.NewMixer(cfg.Audio.SampleRate, cfg.Video.FPS)

	if cfg.Audio.BGM.WavPath != "" {
		bgmPCM, err := audio.LoadWavFile(cfg.Audio.BGM.WavPath)
		if err != nil {
			slog.Error("load bgm", "err", err)
			os.Exit(1)
		}
		mixer.SetBGM(bgmPCM, audio.GainToLinear(cfg.Audio.BGM.GainDB))
		slog.Info("bgm loaded", "samples", len(bgmPCM))
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

	if rel, ok := cfg.Audio.Voices["ReleaseEvent"]; ok && rel.WavPath != "" {
		pcm, err := audio.LoadWavFile(rel.WavPath)
		if err != nil {
			slog.Warn("load release ocean", "err", err)
		} else {
			pcm = audio.ApplyFadeOut(pcm, 0.15)
			mixer.SetReleaseOcean(pcm, audio.GainToLinear(rel.GainDB))
			slog.Info("release ocean loaded", "samples", len(pcm))
		}
	}

	clusterCfg := buildClusterConfig(cfg.Audio.Cluster)

	// --- Start FFmpeg (audio-only) ---
	if err := os.MkdirAll(filepath.Dir(*outputPath), 0755); err != nil {
		slog.Error("create output dir", "err", err)
		os.Exit(1)
	}

	ffmpegArgs := []string{
		"-f", "f32le",
		"-ar", fmt.Sprintf("%d", cfg.Audio.SampleRate),
		"-ac", "2",
		"-i", "pipe:0",
		"-c:a", "aac",
		"-b:a", "192k",
		"-y", *outputPath,
	}
	cmd := exec.Command("ffmpeg", ffmpegArgs...)
	cmd.Stderr = os.Stderr
	stdin, err := cmd.StdinPipe()
	if err != nil {
		slog.Error("ffmpeg stdin pipe", "err", err)
		os.Exit(1)
	}
	if err := cmd.Start(); err != nil {
		slog.Error("start ffmpeg", "err", err)
		os.Exit(1)
	}

	// --- Replay loop (no video, audio only) ---
	tickCh := make(chan replay.Tick, 16)
	engine := replay.New(pack, tickCh)
	startSec := replay.CurrentSecond()
	go engine.RunFrom(startSec, 0, time.Millisecond) // fast replay (no wall-clock wait)

	frameTicker := time.NewTicker(time.Millisecond) // render as fast as possible
	defer frameTicker.Stop()

	framesTarget := int(dur.Seconds() * float64(cfg.Video.FPS))
	frameCount := 0
	lastSecond := -1
	var currentTick replay.Tick
	startTime := time.Now()

	for frameCount < framesTarget {
		select {
		case t, ok := <-tickCh:
			if !ok {
				goto done
			}
			currentTick = t
		case <-frameTicker.C:
			if currentTick.Second != lastSecond {
				entries := make([]audio.EventEntry, len(currentTick.Events))
				for i, ev := range currentTick.Events {
					entries[i] = audio.EventEntry{TypeID: ev.TypeID, Weight: ev.Weight}
				}
				triggers := audio.Assign(entries, clusterCfg)
				mixer.ScheduleNotes(triggers)
				lastSecond = currentTick.Second
			}

			samples := mixer.RenderFrame(nil)
			buf := pcmToBytes(samples)
			if _, err := stdin.Write(buf); err != nil {
				slog.Error("write audio", "err", err)
				goto done
			}
			frameCount++

			if frameCount%cfg.Video.FPS == 0 {
				elapsed := time.Since(startTime)
				rendered := time.Duration(frameCount) * time.Second / time.Duration(cfg.Video.FPS)
				slog.Info("progress",
					"rendered", rendered.Truncate(time.Second),
					"target", dur,
					"elapsed", elapsed.Truncate(time.Millisecond),
				)
			}
		}
	}

done:
	stdin.Close()
	if err := cmd.Wait(); err != nil {
		slog.Error("ffmpeg wait", "err", err)
		os.Exit(1)
	}
	slog.Info("done", "output", *outputPath, "frames", frameCount)
}

func pcmToBytes(samples []float32) []byte {
	buf := make([]byte, len(samples)*4)
	for i, s := range samples {
		binary.LittleEndian.PutUint32(buf[i*4:], math.Float32bits(s))
	}
	return buf
}

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
		p := filepath.Join(daypackDir, e.Name(), "day.bin")
		if _, serr := os.Stat(p); serr == nil {
			dirs = append(dirs, e.Name())
		}
	}
	if len(dirs) == 0 {
		return "", "", fmt.Errorf("no daypack found in %q", daypackDir)
	}
	sort.Strings(dirs)
	latest := dirs[len(dirs)-1]
	return filepath.Join(daypackDir, latest, "day.bin"), latest, nil
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
