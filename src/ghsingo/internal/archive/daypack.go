package archive

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"
)

const (
	HeaderSize       = 16
	MaxEventsPerTick = 4
	MaxTextLen       = 64
	TotalTicks       = 86400
)

var magic = [4]byte{'G', 'S', 'I', 'N'}

// Header is the 16-byte file header for a day-pack binary.
type Header struct {
	Magic      [4]byte // "GSIN"
	Version    uint16
	Date       uint32 // YYYYMMDD
	TotalTicks uint32 // always 86400
	Reserved   [2]byte
}

// Event represents a single GitHub event mapped to a second slot.
type Event struct {
	TypeID uint8  // 0~5
	Weight uint8  // 0~255
	Text   string // max 64 bytes UTF-8
}

// Tick holds up to MaxEventsPerTick events for a given second-of-day.
type Tick struct {
	Events []Event // 0~4
}

// Daypack is the full in-memory representation of a .bin day file.
type Daypack struct {
	Header Header
	Ticks  []Tick
}

// WriteDaypack serializes a Daypack to a binary file at path.
func WriteDaypack(path string, pack *Daypack) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create daypack: %w", err)
	}
	defer f.Close()

	// Write header.
	if err := binary.Write(f, binary.LittleEndian, pack.Header.Magic); err != nil {
		return err
	}
	if err := binary.Write(f, binary.LittleEndian, pack.Header.Version); err != nil {
		return err
	}
	if err := binary.Write(f, binary.LittleEndian, pack.Header.Date); err != nil {
		return err
	}
	if err := binary.Write(f, binary.LittleEndian, pack.Header.TotalTicks); err != nil {
		return err
	}
	if err := binary.Write(f, binary.LittleEndian, pack.Header.Reserved); err != nil {
		return err
	}

	// Ensure Ticks slice is exactly TotalTicks long for writing.
	ticks := pack.Ticks
	if len(ticks) < TotalTicks {
		ticks = make([]Tick, TotalTicks)
		copy(ticks, pack.Ticks)
	}

	for i := 0; i < TotalTicks; i++ {
		t := ticks[i]
		n := len(t.Events)
		if n > MaxEventsPerTick {
			n = MaxEventsPerTick
		}
		if _, err := f.Write([]byte{byte(n)}); err != nil {
			return err
		}
		for j := 0; j < n; j++ {
			ev := t.Events[j]
			text := truncateUTF8(ev.Text, MaxTextLen)
			tl := len(text)
			buf := []byte{ev.TypeID, ev.Weight, byte(tl)}
			if _, werr := f.Write(buf); werr != nil {
				return werr
			}
			if tl > 0 {
				if _, werr := f.Write([]byte(text)); werr != nil {
					return werr
				}
			}
		}
	}
	return nil
}

// ReadDaypack deserializes a Daypack from a binary file, validating the magic bytes.
func ReadDaypack(path string) (*Daypack, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open daypack: %w", err)
	}
	defer f.Close()

	var h Header
	if err := binary.Read(f, binary.LittleEndian, &h.Magic); err != nil {
		return nil, fmt.Errorf("read magic: %w", err)
	}
	if h.Magic != magic {
		return nil, fmt.Errorf("bad magic: got %q, want %q", h.Magic, magic)
	}
	if err := binary.Read(f, binary.LittleEndian, &h.Version); err != nil {
		return nil, err
	}
	if err := binary.Read(f, binary.LittleEndian, &h.Date); err != nil {
		return nil, err
	}
	if err := binary.Read(f, binary.LittleEndian, &h.TotalTicks); err != nil {
		return nil, err
	}
	if err := binary.Read(f, binary.LittleEndian, &h.Reserved); err != nil {
		return nil, err
	}

	ticks := make([]Tick, h.TotalTicks)
	for i := uint32(0); i < h.TotalTicks; i++ {
		var countBuf [1]byte
		if _, err := io.ReadFull(f, countBuf[:]); err != nil {
			return nil, fmt.Errorf("tick %d count: %w", i, err)
		}
		n := int(countBuf[0])
		if n > MaxEventsPerTick {
			return nil, fmt.Errorf("tick %d: event count %d exceeds max %d", i, n, MaxEventsPerTick)
		}
		if n == 0 {
			continue
		}
		events := make([]Event, n)
		for j := 0; j < n; j++ {
			var meta [3]byte // type_id, weight, text_len
			if _, err := io.ReadFull(f, meta[:]); err != nil {
				return nil, fmt.Errorf("tick %d event %d meta: %w", i, j, err)
			}
			tl := int(meta[2])
			var text string
			if tl > 0 {
				tb := make([]byte, tl)
				if _, err := io.ReadFull(f, tb); err != nil {
					return nil, fmt.Errorf("tick %d event %d text: %w", i, j, err)
				}
				text = string(tb)
			}
			events[j] = Event{
				TypeID: meta[0],
				Weight: meta[1],
				Text:   text,
			}
		}
		ticks[i].Events = events
	}

	return &Daypack{Header: h, Ticks: ticks}, nil
}

// truncateUTF8 truncates s to at most maxBytes bytes without breaking UTF-8.
func truncateUTF8(s string, maxBytes int) string {
	if len(s) <= maxBytes {
		return s
	}
	// Walk backwards to find a valid UTF-8 boundary.
	b := []byte(s)
	for maxBytes > 0 && maxBytes < len(b) && b[maxBytes]>>6 == 0b10 {
		maxBytes--
	}
	return string(b[:maxBytes])
}

// Write method on *os.File returns (int, error); binary.Write helper used above
// returns just error. The bare f.Write calls use the (int, error) signature.
// We wrap single-byte writes for the count byte via the slice form.
