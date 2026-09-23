package replay

import (
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
)

// Tick is emitted by the Engine for each second-of-day.
type Tick struct {
	Second int
	Events []archive.Event
}

// Engine replays a Daypack by emitting one Tick per second into a channel.
type Engine struct {
	pack *archive.Daypack
	ch   chan<- Tick
}

// New creates a replay Engine that will emit ticks from pack into ch.
func New(pack *archive.Daypack, ch chan<- Tick) *Engine {
	return &Engine{pack: pack, ch: ch}
}

// RunFrom starts emitting ticks from startSec.
// tickInterval controls pacing (time.Second for real-time, time.Millisecond for tests).
// maxTicks = 0 means infinite (wrap around at end of day).
// Closes ch when done (maxTicks reached).
// Wraps around: after second 86399, goes back to 0.
func (e *Engine) RunFrom(startSec int, maxTicks int, tickInterval time.Duration) {
	defer close(e.ch)

	sec := startSec % archive.TotalTicks
	emitted := 0

	for {
		if maxTicks > 0 && emitted >= maxTicks {
			return
		}

		idx := sec % archive.TotalTicks
		var events []archive.Event
		if idx < len(e.pack.Ticks) {
			events = e.pack.Ticks[idx].Events
		}
		t := Tick{
			Second: idx,
			Events: events,
		}
		e.ch <- t

		emitted++
		sec = (sec + 1) % archive.TotalTicks

		// Sleep between ticks (skip sleep after the last tick).
		if maxTicks == 0 || emitted < maxTicks {
			time.Sleep(tickInterval)
		}
	}
}

// CurrentSecond returns the current wall-clock second-of-day
// (hour*3600 + minute*60 + second).
func CurrentSecond() int {
	now := time.Now()
	return now.Hour()*3600 + now.Minute()*60 + now.Second()
}
