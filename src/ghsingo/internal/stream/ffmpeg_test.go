package stream

import (
	"os/exec"
	"testing"
)

func assertContains(t *testing.T, args []string, key, val string) {
	t.Helper()
	for i, a := range args {
		if a == key && i+1 < len(args) && args[i+1] == val {
			return
		}
	}
	t.Errorf("args missing %s %s", key, val)
}

func TestBuildLocalArgs(t *testing.T) {
	opts := Options{
		Width:            1280,
		Height:           720,
		FPS:              30,
		VideoPreset:      "ultrafast",
		AudioBitrateKbps: 128,
		SampleRate:       44100,
		Mode:             "local",
		OutputPath:       "/tmp/test.flv",
	}

	args := BuildArgs(opts)

	assertContains(t, args, "-f", "rawvideo")
	assertContains(t, args, "-pix_fmt", "rgba")
	assertContains(t, args, "-s", "1280x720")
	assertContains(t, args, "-preset", "ultrafast")
	assertContains(t, args, "-b:a", "128k")

	if last := args[len(args)-1]; last != "/tmp/test.flv" {
		t.Errorf("last arg = %q; want /tmp/test.flv", last)
	}
}

func TestBuildRTMPSArgs(t *testing.T) {
	url := "rtmps://a.rtmps.youtube.com/live2/KEY"
	opts := Options{
		Width:            1920,
		Height:           1080,
		FPS:              30,
		VideoPreset:      "veryfast",
		AudioBitrateKbps: 160,
		SampleRate:       48000,
		Mode:             "rtmps",
		RTMPSURL:         url,
	}

	args := BuildArgs(opts)

	if last := args[len(args)-1]; last != url {
		t.Errorf("last arg = %q; want %s", last, url)
	}
	assertContains(t, args, "-f", "flv")
}

func TestFFmpegExists(t *testing.T) {
	path, err := exec.LookPath("ffmpeg")
	if err != nil {
		t.Skip("ffmpeg not found in PATH, skipping")
	}
	t.Logf("ffmpeg found at %s", path)
}
