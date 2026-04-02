package stream

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
)

// Options configures the FFmpeg subprocess for streaming or local recording.
type Options struct {
	Width            int
	Height           int
	FPS              int
	VideoPreset      string
	VideoBitrateKbps int // 0 = CRF mode (FFmpeg default)
	AudioBitrateKbps int
	SampleRate       int
	Mode             string // "local" or "rtmps"
	OutputPath       string // for mode=local
	RTMPSURL         string // for mode=rtmps
}

// BuildArgs builds the FFmpeg argument list.
//
// Video input:  -f rawvideo -pix_fmt rgba -s WxH -r FPS -i pipe:0
// Audio input:  -f f32le -ar RATE -ac 2 -i pipe:3
// Video encode: -c:v libx264 -preset PRESET -tune zerolatency -pix_fmt yuv420p -g FPS*2
// Audio encode: -c:a aac -b:a BITRATEk
// General:      -shortest -y
// Output:       mode=local -> filepath, mode=rtmps -> -f flv RTMPS_URL
func BuildArgs(opts Options) []string {
	args := []string{
		// Video input
		"-f", "rawvideo",
		"-pix_fmt", "rgba",
		"-s", fmt.Sprintf("%dx%d", opts.Width, opts.Height),
		"-r", fmt.Sprintf("%d", opts.FPS),
		"-i", "pipe:0",
		// Audio input
		"-f", "f32le",
		"-ar", fmt.Sprintf("%d", opts.SampleRate),
		"-ac", "2",
		"-i", "pipe:3",
		// Video encode
		"-c:v", "libx264",
		"-preset", opts.VideoPreset,
		"-tune", "zerolatency",
		"-pix_fmt", "yuv420p",
		"-g", fmt.Sprintf("%d", opts.FPS*2),
	}
	if opts.VideoBitrateKbps > 0 {
		args = append(args,
			"-b:v", fmt.Sprintf("%dk", opts.VideoBitrateKbps),
			"-maxrate", fmt.Sprintf("%dk", opts.VideoBitrateKbps),
			"-bufsize", fmt.Sprintf("%dk", opts.VideoBitrateKbps*2),
		)
	}
	args = append(args,
		// Audio encode
		"-c:a", "aac",
		"-b:a", fmt.Sprintf("%dk", opts.AudioBitrateKbps),
		// General
		"-shortest",
		"-y",
	)

	switch opts.Mode {
	case "rtmps":
		args = append(args, "-f", "flv", opts.RTMPSURL)
	default: // "local"
		args = append(args, opts.OutputPath)
	}

	return args
}

// Manager owns the FFmpeg subprocess and its stdin/extra-fd pipes.
type Manager struct {
	opts  Options
	cmd   *exec.Cmd
	video io.WriteCloser // pipe:0 (stdin)
	audio io.WriteCloser // pipe:3 (extra fd)
}

// NewManager creates a Manager but does not start the subprocess.
func NewManager(opts Options) *Manager {
	return &Manager{opts: opts}
}

// Start launches the FFmpeg subprocess.
// video pipe = cmd.StdinPipe()
// audio pipe = os.Pipe(), passed via cmd.ExtraFiles (becomes fd 3 in the child).
// The read end of the audio pipe is closed in the parent after Start.
func (m *Manager) Start() error {
	args := BuildArgs(m.opts)
	m.cmd = exec.Command("ffmpeg", args...)

	// Video pipe via stdin.
	videoPipe, err := m.cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("stream: stdin pipe: %w", err)
	}
	m.video = videoPipe

	// Audio pipe via extra fd (fd 3 in child).
	audioR, audioW, err := os.Pipe()
	if err != nil {
		return fmt.Errorf("stream: os.Pipe: %w", err)
	}
	m.cmd.ExtraFiles = []*os.File{audioR} // index 0 -> fd 3
	m.audio = audioW

	// Discard stderr/stdout to avoid blocking; log via slog.
	m.cmd.Stderr = os.Stderr
	m.cmd.Stdout = os.Stdout

	if err := m.cmd.Start(); err != nil {
		return fmt.Errorf("stream: ffmpeg start: %w", err)
	}
	slog.Info("ffmpeg started", "pid", m.cmd.Process.Pid, "mode", m.opts.Mode)

	// Parent must close the read end; child inherited it.
	audioR.Close()

	return nil
}

// WriteVideo sends raw RGBA frame data to FFmpeg's stdin (pipe:0).
func (m *Manager) WriteVideo(data []byte) error {
	if m.video == nil {
		return fmt.Errorf("stream: video pipe not initialised")
	}
	_, err := m.video.Write(data)
	return err
}

// WriteAudio sends f32le interleaved audio samples to FFmpeg's fd 3.
func (m *Manager) WriteAudio(data []byte) error {
	if m.audio == nil {
		return fmt.Errorf("stream: audio pipe not initialised")
	}
	_, err := m.audio.Write(data)
	return err
}

// Stop closes both pipes and waits for the FFmpeg process to exit.
func (m *Manager) Stop() error {
	var firstErr error

	if m.video != nil {
		if err := m.video.Close(); err != nil && firstErr == nil {
			firstErr = fmt.Errorf("stream: close video pipe: %w", err)
		}
	}
	if m.audio != nil {
		if err := m.audio.Close(); err != nil && firstErr == nil {
			firstErr = fmt.Errorf("stream: close audio pipe: %w", err)
		}
	}
	if m.cmd != nil {
		if err := m.cmd.Wait(); err != nil && firstErr == nil {
			firstErr = fmt.Errorf("stream: ffmpeg wait: %w", err)
		}
		slog.Info("ffmpeg stopped", "mode", m.opts.Mode)
	}

	return firstErr
}
