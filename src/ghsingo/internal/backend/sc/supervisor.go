package sc

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os/exec"
	"sync"
	"sync/atomic"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/backend/sc/osc"
)

// ProcessStarter is injected so tests can run a Supervisor without
// needing a real scsynth binary on PATH. Production callers use
// scsynthStarter (defined in sc.go).
type ProcessStarter func(ctx context.Context) (*exec.Cmd, error)

// Supervisor owns the lifetime of a scsynth subprocess and (in
// production) opens a UDP socket to send /s_new / /n_set / /status to it.
//
// Auto-restart contract: if the subprocess exits, the supervisor brings
// up a new one with the same starter. RestartCount records how many
// recoveries have happened so #36 (lifecycle decoupling) can surface
// it as a metric without ffmpeg ever knowing.
type Supervisor struct {
	starter      ProcessStarter
	udpAddr      *net.UDPAddr
	conn         *net.UDPConn
	heartbeatTTL time.Duration

	mu           sync.Mutex
	cmd          *exec.Cmd
	cancel       context.CancelFunc
	restartCount int64
	closed       atomic.Bool
}

// SupervisorOptions configures a new Supervisor.
type SupervisorOptions struct {
	// Starter spawns the scsynth (or fake) subprocess. Required.
	Starter ProcessStarter
	// Address is the UDP host:port the subprocess listens on (typically
	// "127.0.0.1:57110"). Production code must set this; tests can leave
	// empty to skip the network side.
	Address string
	// HeartbeatTTL is how long we wait for a /status reply before
	// declaring the subprocess wedged. 0 disables the heartbeat check.
	HeartbeatTTL time.Duration
}

// NewSupervisor constructs a Supervisor but does not start the
// subprocess; call Start.
func NewSupervisor(opts SupervisorOptions) (*Supervisor, error) {
	if opts.Starter == nil {
		return nil, errors.New("sc: Supervisor needs a Starter")
	}
	s := &Supervisor{
		starter:      opts.Starter,
		heartbeatTTL: opts.HeartbeatTTL,
	}
	if opts.Address != "" {
		addr, err := net.ResolveUDPAddr("udp", opts.Address)
		if err != nil {
			return nil, fmt.Errorf("sc: resolve %q: %w", opts.Address, err)
		}
		s.udpAddr = addr
	}
	return s, nil
}

// Start launches the subprocess and (if Address was set) opens the UDP
// socket. Subsequent failures crash-loop the subprocess.
func (s *Supervisor) Start(ctx context.Context) error {
	if s.closed.Load() {
		return errors.New("sc: supervisor closed")
	}

	if s.udpAddr != nil {
		conn, err := net.DialUDP("udp", nil, s.udpAddr)
		if err != nil {
			return fmt.Errorf("sc: dial %v: %w", s.udpAddr, err)
		}
		s.conn = conn
	}

	if err := s.spawn(ctx); err != nil {
		return err
	}
	go s.watch(ctx)
	return nil
}

// Send dispatches one OSC message to the subprocess. Returns an error
// if the supervisor has no UDP connection (e.g. test-only mode).
func (s *Supervisor) Send(m osc.Message) error {
	if s.conn == nil {
		return errors.New("sc: no UDP connection (test mode?)")
	}
	body, err := m.Encode()
	if err != nil {
		return err
	}
	_, err = s.conn.Write(body)
	return err
}

// SendBundle dispatches one OSC bundle.
func (s *Supervisor) SendBundle(b osc.Bundle) error {
	if s.conn == nil {
		return errors.New("sc: no UDP connection (test mode?)")
	}
	body, err := b.Encode()
	if err != nil {
		return err
	}
	_, err = s.conn.Write(body)
	return err
}

// RestartCount reports how many times the subprocess has been
// auto-restarted.
func (s *Supervisor) RestartCount() int64 { return atomic.LoadInt64(&s.restartCount) }

// Close terminates the subprocess and releases the UDP socket. It is
// idempotent.
func (s *Supervisor) Close() error {
	if !s.closed.CompareAndSwap(false, true) {
		return nil
	}
	s.mu.Lock()
	if s.cancel != nil {
		s.cancel()
	}
	cmd := s.cmd
	s.mu.Unlock()
	if cmd != nil && cmd.Process != nil {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}
	if s.conn != nil {
		_ = s.conn.Close()
	}
	return nil
}

func (s *Supervisor) spawn(parent context.Context) error {
	ctx, cancel := context.WithCancel(parent)
	cmd, err := s.starter(ctx)
	if err != nil {
		cancel()
		return err
	}
	s.mu.Lock()
	s.cmd = cmd
	s.cancel = cancel
	s.mu.Unlock()
	return nil
}

func (s *Supervisor) watch(parent context.Context) {
	for {
		s.mu.Lock()
		cmd := s.cmd
		s.mu.Unlock()
		if cmd == nil {
			return
		}
		_ = cmd.Wait()
		if s.closed.Load() {
			return
		}
		// subprocess exited unexpectedly — restart
		atomic.AddInt64(&s.restartCount, 1)
		// small backoff so a wedged binary doesn't spin
		select {
		case <-time.After(500 * time.Millisecond):
		case <-parent.Done():
			return
		}
		if err := s.spawn(parent); err != nil {
			// Fatal: starter itself failing is unrecoverable.
			return
		}
	}
}
