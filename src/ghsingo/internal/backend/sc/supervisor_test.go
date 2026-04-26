package sc

import (
	"context"
	"errors"
	"os/exec"
	"testing"
	"time"
)

// TestSupervisorAutoRestart spawns a short-lived "scsynth" (in fact /bin/true)
// and verifies the supervisor auto-restarts it.
func TestSupervisorAutoRestart(t *testing.T) {
	calls := 0
	starter := func(ctx context.Context) (*exec.Cmd, error) {
		calls++
		// /bin/true exits immediately, simulating a crash loop.
		cmd := exec.CommandContext(ctx, "/bin/true")
		if err := cmd.Start(); err != nil {
			return nil, err
		}
		return cmd, nil
	}
	sup, err := NewSupervisor(SupervisorOptions{Starter: starter})
	if err != nil {
		t.Fatal(err)
	}
	if err := sup.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer sup.Close()

	deadline := time.After(3 * time.Second)
	for {
		select {
		case <-deadline:
			t.Fatalf("supervisor never restarted; calls=%d restarts=%d", calls, sup.RestartCount())
		default:
			if sup.RestartCount() >= 1 {
				return
			}
			time.Sleep(50 * time.Millisecond)
		}
	}
}

// TestSupervisorStarterFailureSurfaces ensures a Starter that returns an
// error from Start gets bubbled up to the caller.
func TestSupervisorStarterFailureSurfaces(t *testing.T) {
	starter := func(ctx context.Context) (*exec.Cmd, error) {
		return nil, errors.New("simulated starter failure")
	}
	sup, err := NewSupervisor(SupervisorOptions{Starter: starter})
	if err != nil {
		t.Fatal(err)
	}
	defer sup.Close()
	if err := sup.Start(context.Background()); err == nil {
		t.Fatal("expected starter failure to surface")
	}
}

// TestSupervisorCloseIdempotent verifies Close is safe to call twice.
func TestSupervisorCloseIdempotent(t *testing.T) {
	starter := func(ctx context.Context) (*exec.Cmd, error) {
		cmd := exec.CommandContext(ctx, "/bin/sleep", "30")
		if err := cmd.Start(); err != nil {
			return nil, err
		}
		return cmd, nil
	}
	sup, err := NewSupervisor(SupervisorOptions{Starter: starter})
	if err != nil {
		t.Fatal(err)
	}
	if err := sup.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := sup.Close(); err != nil {
		t.Fatal(err)
	}
	if err := sup.Close(); err != nil {
		t.Fatalf("second close returned %v", err)
	}
}
