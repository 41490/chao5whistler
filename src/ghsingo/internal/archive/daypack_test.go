package archive

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDaypackRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "day.bin")

	original := &Daypack{
		Header: Header{
			Magic:      [4]byte{'G', 'S', 'I', 'N'},
			Version:    1,
			Date:       20260329,
			TotalTicks: TotalTicks,
		},
		Ticks: make([]Tick, TotalTicks),
	}

	// Events at tick 0.
	original.Ticks[0].Events = []Event{
		{TypeID: 0, Weight: 200, Text: "torvalds/linux"},
		{TypeID: 3, Weight: 150, Text: "rust-lang/rust"},
	}
	// Events at tick 3600.
	original.Ticks[3600].Events = []Event{
		{TypeID: 5, Weight: 255, Text: "golang/go"},
	}

	if err := WriteDaypack(path, original); err != nil {
		t.Fatalf("WriteDaypack: %v", err)
	}

	got, err := ReadDaypack(path)
	if err != nil {
		t.Fatalf("ReadDaypack: %v", err)
	}

	// Verify header fields.
	if got.Header.Magic != original.Header.Magic {
		t.Errorf("magic: got %v, want %v", got.Header.Magic, original.Header.Magic)
	}
	if got.Header.Version != original.Header.Version {
		t.Errorf("version: got %d, want %d", got.Header.Version, original.Header.Version)
	}
	if got.Header.Date != original.Header.Date {
		t.Errorf("date: got %d, want %d", got.Header.Date, original.Header.Date)
	}
	if got.Header.TotalTicks != original.Header.TotalTicks {
		t.Errorf("total_ticks: got %d, want %d", got.Header.TotalTicks, original.Header.TotalTicks)
	}

	// Verify tick 0 events.
	if len(got.Ticks[0].Events) != 2 {
		t.Fatalf("tick[0] events: got %d, want 2", len(got.Ticks[0].Events))
	}
	for i, want := range original.Ticks[0].Events {
		g := got.Ticks[0].Events[i]
		if g.TypeID != want.TypeID || g.Weight != want.Weight || g.Text != want.Text {
			t.Errorf("tick[0] event[%d]: got %+v, want %+v", i, g, want)
		}
	}

	// Verify tick 3600 events.
	if len(got.Ticks[3600].Events) != 1 {
		t.Fatalf("tick[3600] events: got %d, want 1", len(got.Ticks[3600].Events))
	}
	g := got.Ticks[3600].Events[0]
	want := original.Ticks[3600].Events[0]
	if g.TypeID != want.TypeID || g.Weight != want.Weight || g.Text != want.Text {
		t.Errorf("tick[3600] event[0]: got %+v, want %+v", g, want)
	}

	// Verify empty ticks stay empty.
	if len(got.Ticks[1].Events) != 0 {
		t.Errorf("tick[1] should be empty, got %d events", len(got.Ticks[1].Events))
	}
}

func TestDaypackBadMagic(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.bin")

	if err := os.WriteFile(path, []byte("JUNK_DATA_HERE__padding_to_be_long_enough"), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := ReadDaypack(path)
	if err == nil {
		t.Fatal("expected error for bad magic, got nil")
	}
	t.Logf("got expected error: %v", err)
}

func TestDaypackFileSize(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "sparse.bin")

	pack := &Daypack{
		Header: Header{
			Magic:      [4]byte{'G', 'S', 'I', 'N'},
			Version:    1,
			Date:       20260329,
			TotalTicks: TotalTicks,
		},
		Ticks: make([]Tick, TotalTicks),
	}

	// Scatter 100 events across the day.
	for i := 0; i < 100; i++ {
		sec := i * 864 // spread across 86400
		pack.Ticks[sec].Events = []Event{
			{TypeID: uint8(i % 6), Weight: uint8(i * 2 % 256), Text: "some/repo"},
		}
	}

	if err := WriteDaypack(path, pack); err != nil {
		t.Fatalf("WriteDaypack: %v", err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}

	// 86400 ticks * 1 byte count + 16 header = ~86416 bytes baseline
	// plus 100 events * ~13 bytes each = ~87716 bytes
	// Should be well under 200KB.
	const maxSize = 200 * 1024
	if info.Size() > maxSize {
		t.Errorf("file size %d bytes exceeds %d byte limit", info.Size(), maxSize)
	}
	t.Logf("sparse pack file size: %d bytes", info.Size())
}
