// Package osc is a minimal OSC 1.0 encoder for the scsynth backend
// (#35). It supports just the four type tags ghsingo needs to drive
// scsynth: int32 (i), float32 (f), string (s), and bundles (#bundle).
//
// Why hand-rolled? scsynth control is a tiny corner of OSC; importing
// a third-party OSC library for it would drag in network helpers,
// timetag math, and address-pattern matching we never use. About 100
// lines of pure encoding keeps the surface honest and unit-testable.
package osc

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"math"
)

// Message is a single OSC message: address + heterogeneous args.
type Message struct {
	Address string
	Args    []any
}

// Encode produces the wire-format bytes for one Message. Unsupported
// argument types return an error rather than silently dropping.
func (m Message) Encode() ([]byte, error) {
	var buf bytes.Buffer
	if err := writeOSCString(&buf, m.Address); err != nil {
		return nil, err
	}
	tag := ","
	for _, a := range m.Args {
		switch a.(type) {
		case int32:
			tag += "i"
		case float32:
			tag += "f"
		case string:
			tag += "s"
		default:
			return nil, fmt.Errorf("osc: unsupported arg type %T", a)
		}
	}
	if err := writeOSCString(&buf, tag); err != nil {
		return nil, err
	}
	for _, a := range m.Args {
		switch v := a.(type) {
		case int32:
			if err := binary.Write(&buf, binary.BigEndian, v); err != nil {
				return nil, err
			}
		case float32:
			if err := binary.Write(&buf, binary.BigEndian, math.Float32bits(v)); err != nil {
				return nil, err
			}
		case string:
			if err := writeOSCString(&buf, v); err != nil {
				return nil, err
			}
		}
	}
	return buf.Bytes(), nil
}

// Bundle wraps a list of Messages with a (currently always-immediate)
// timetag.
type Bundle struct {
	Messages []Message
}

// Encode produces the wire-format bytes for one Bundle. The timetag is
// the OSC sentinel "immediate" (1 in the fractional half).
func (b Bundle) Encode() ([]byte, error) {
	var buf bytes.Buffer
	if err := writeOSCString(&buf, "#bundle"); err != nil {
		return nil, err
	}
	// timetag: seconds=0, frac=1 == immediate
	if err := binary.Write(&buf, binary.BigEndian, uint32(0)); err != nil {
		return nil, err
	}
	if err := binary.Write(&buf, binary.BigEndian, uint32(1)); err != nil {
		return nil, err
	}
	for _, m := range b.Messages {
		body, err := m.Encode()
		if err != nil {
			return nil, err
		}
		if err := binary.Write(&buf, binary.BigEndian, uint32(len(body))); err != nil {
			return nil, err
		}
		buf.Write(body)
	}
	return buf.Bytes(), nil
}

// writeOSCString writes a NUL-terminated, 4-byte-aligned string.
func writeOSCString(w *bytes.Buffer, s string) error {
	if _, err := w.WriteString(s); err != nil {
		return err
	}
	// always at least one NUL terminator
	w.WriteByte(0)
	pad := (4 - ((len(s) + 1) % 4)) % 4
	for i := 0; i < pad; i++ {
		w.WriteByte(0)
	}
	return nil
}
