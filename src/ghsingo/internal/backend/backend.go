// Package backend defines the audio-engine boundary for ghsingo v2.
//
// A Backend is the only thing cmd/live-v2 / cmd/render-audio-v2 / future
// soak harnesses need to know about. It hides whether sound is produced
// by the in-process Go MixerV2 (this package's gov2 sub-package) or by
// an external scsynth supervisor (#35) or anything else. Per #34, the
// goal is to take the bell-era trigger pipeline out of every main loop
// — once a process holds a Backend it should never reach into mixer or
// composer types directly.
package backend

// Event is the per-tick GH-event payload, copied here so backends do not
// need to depend on internal/composer.
type Event struct {
	TypeID uint8
	Weight uint8
}

// Backend is the audio-engine contract.
//
// Lifecycle: Init -> repeated (ApplyEventsForSecond + N RenderFrame) -> Close.
//
// One Tick in caller time is one data-second's worth of events; ApplyEventsForSecond
// is called once per data-second, and RenderFrame is called repeatedly to drain
// the audio (typically Video.FPS frames per second of output).
type Backend interface {
	// Init prepares any external runtime (synth supervisor, OSC ports,
	// etc.). Must be idempotent on repeat call from the same caller.
	Init() error

	// Close releases resources. Always safe to call once after Init,
	// idempotent on repeat call.
	Close() error

	// ApplyEventsForSecond folds one second of GH events into the
	// engine's slow state and queues any sparse accents for the next
	// RenderFrame slot.
	ApplyEventsForSecond(events []Event)

	// RenderFrame returns SamplesPerFrame() * 2 stereo float32 samples
	// (interleaved L/R). The slice is owned by the backend and may be
	// overwritten on the next call.
	RenderFrame() ([]float32, error)

	// SampleRate returns the backend's PCM sample rate.
	SampleRate() int

	// SamplesPerFrame returns the count of mono samples per channel per
	// frame. The interleaved RenderFrame slice has 2× this length.
	SamplesPerFrame() int

	// Name returns a short identifier ("go-v2", "scsynth", ...).
	Name() string
}
