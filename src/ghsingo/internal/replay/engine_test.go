package replay

import (
	"testing"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
)

// newDaypack creates a Daypack with a full 86400-element Ticks slice.
func newDaypack() *archive.Daypack {
	return &archive.Daypack{
		Ticks: make([]archive.Tick, archive.TotalTicks),
	}
}

func TestEngineEmitsTicks(t *testing.T) {
	pack := newDaypack()
	pack.Ticks[0].Events = []archive.Event{{TypeID: 1, Weight: 10, Text: "foo/bar"}}
	pack.Ticks[1].Events = []archive.Event{{TypeID: 2, Weight: 5, Text: "baz/qux"}}

	ch := make(chan Tick, 4)
	eng := New(pack, ch)

	go eng.RunFrom(0, 2, time.Millisecond)

	tick0 := <-ch
	if tick0.Second != 0 {
		t.Fatalf("tick0.Second = %d, want 0", tick0.Second)
	}
	if len(tick0.Events) != 1 || tick0.Events[0].TypeID != 1 {
		t.Fatalf("tick0.Events = %v, want [{TypeID:1 Weight:10 Text:foo/bar}]", tick0.Events)
	}

	tick1 := <-ch
	if tick1.Second != 1 {
		t.Fatalf("tick1.Second = %d, want 1", tick1.Second)
	}
	if len(tick1.Events) != 1 || tick1.Events[0].TypeID != 2 {
		t.Fatalf("tick1.Events = %v, want [{TypeID:2 Weight:5 Text:baz/qux}]", tick1.Events)
	}

	// Channel should be closed after maxTicks reached.
	_, ok := <-ch
	if ok {
		t.Fatal("channel should be closed after maxTicks reached")
	}
}

func TestEngineWrapsAtEndOfDay(t *testing.T) {
	pack := newDaypack()
	pack.Ticks[86399].Events = []archive.Event{{TypeID: 0, Weight: 1, Text: "wrap/test"}}
	pack.Ticks[0].Events = []archive.Event{{TypeID: 3, Weight: 2, Text: "wrap/zero"}}

	ch := make(chan Tick, 4)
	eng := New(pack, ch)

	go eng.RunFrom(86399, 3, time.Millisecond)

	tick0 := <-ch
	if tick0.Second != 86399 {
		t.Fatalf("tick0.Second = %d, want 86399", tick0.Second)
	}
	if len(tick0.Events) != 1 || tick0.Events[0].Text != "wrap/test" {
		t.Fatalf("tick0.Events = %v, want [{TypeID:0 Weight:1 Text:wrap/test}]", tick0.Events)
	}

	tick1 := <-ch
	if tick1.Second != 0 {
		t.Fatalf("tick1.Second = %d, want 0 (wrapped)", tick1.Second)
	}
	if len(tick1.Events) != 1 || tick1.Events[0].Text != "wrap/zero" {
		t.Fatalf("tick1.Events = %v, want [{TypeID:3 Weight:2 Text:wrap/zero}]", tick1.Events)
	}

	tick2 := <-ch
	if tick2.Second != 1 {
		t.Fatalf("tick2.Second = %d, want 1", tick2.Second)
	}

	// Channel closed after 3 ticks.
	_, ok := <-ch
	if ok {
		t.Fatal("channel should be closed after maxTicks reached")
	}
}
