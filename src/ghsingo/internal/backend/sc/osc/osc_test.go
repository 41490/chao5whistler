package osc

import (
	"bytes"
	"testing"
)

// TestEncodeStatus verifies the simplest scsynth control message:
// "/status" with no args. Reference encoded form taken from the OSC 1.0
// spec; "/status\0" + ",\0\0\0".
func TestEncodeStatus(t *testing.T) {
	got, err := Message{Address: "/status"}.Encode()
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	want := []byte{
		'/', 's', 't', 'a', 't', 'u', 's', 0,
		',', 0, 0, 0,
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("encoded %v, want %v", got, want)
	}
}

// TestEncodeSNew exercises the four argument type tags ghsingo uses
// to drive scsynth: /s_new with name string + node int + addAction int +
// targetGroup int + (defName float would never happen, but we add a
// float to confirm the encoder).
func TestEncodeSNew(t *testing.T) {
	m := Message{
		Address: "/s_new",
		Args:    []any{"drone", int32(1000), int32(0), int32(1), float32(220.0)},
	}
	got, err := m.Encode()
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	// Must start with /s_new + NUL + padding to 4 bytes.
	if !bytes.HasPrefix(got, []byte("/s_new\x00\x00")) {
		t.Fatalf("missing /s_new prefix: %q", got[:8])
	}
	// Type tag string ",siiif" + 2 nul pad to 8 bytes (",siiif\x00\x00").
	if !bytes.Contains(got, []byte(",siiif\x00\x00")) {
		t.Fatalf("missing type tag ,siiif: %v", got)
	}
}

// TestEncodeBundle verifies a 2-message immediate bundle: prefix
// "#bundle\0" + 8-byte timetag (0, 1) + per-message length-prefixed body.
func TestEncodeBundle(t *testing.T) {
	b := Bundle{Messages: []Message{
		{Address: "/x", Args: []any{int32(1)}},
		{Address: "/y", Args: []any{float32(2.5)}},
	}}
	got, err := b.Encode()
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	if !bytes.HasPrefix(got, []byte("#bundle\x00")) {
		t.Fatalf("missing #bundle prefix")
	}
	// Bundle timetag: 0x00000000 0x00000001
	tt := got[8:16]
	if !bytes.Equal(tt, []byte{0, 0, 0, 0, 0, 0, 0, 1}) {
		t.Fatalf("timetag = %v, want 0/1", tt)
	}
}

// TestEncodeRejectsUnsupportedType ensures we fail fast rather than
// silently emitting a wrong type tag.
func TestEncodeRejectsUnsupportedType(t *testing.T) {
	_, err := Message{Address: "/x", Args: []any{int64(1)}}.Encode()
	if err == nil {
		t.Fatal("expected error for int64 arg")
	}
}
