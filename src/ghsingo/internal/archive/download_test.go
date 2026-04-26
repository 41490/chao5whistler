package archive

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"testing"
	"time"
)

func TestDownloadMissingHoursDownloadsOnlyMissing(t *testing.T) {
	dir := t.TempDir()
	existingPath := HourFilePath(dir, "2026-04-25", 16)
	if err := os.WriteFile(existingPath, []byte("existing"), 0644); err != nil {
		t.Fatal(err)
	}

	var mu sync.Mutex
	var hits []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		hits = append(hits, r.URL.Path)
		mu.Unlock()
		if r.URL.Path != "/2026-04-25-17.json.gz" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte("downloaded"))
	}))
	defer srv.Close()

	err := DownloadMissingHours(DownloadOptions{
		BaseURL:     srv.URL,
		TargetDate:  "2026-04-25",
		SourceDir:   dir,
		Hours:       []int{16, 17},
		Timeout:     5 * time.Second,
		MaxParallel: 2,
		UserAgent:   "ghsingo-test",
	})
	if err != nil {
		t.Fatalf("DownloadMissingHours: %v", err)
	}

	gotExisting, err := os.ReadFile(existingPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(gotExisting) != "existing" {
		t.Fatalf("existing file overwritten: got %q", string(gotExisting))
	}

	gotDownloaded, err := os.ReadFile(HourFilePath(dir, "2026-04-25", 17))
	if err != nil {
		t.Fatal(err)
	}
	if string(gotDownloaded) != "downloaded" {
		t.Fatalf("downloaded file = %q, want %q", string(gotDownloaded), "downloaded")
	}

	mu.Lock()
	defer mu.Unlock()
	if !slices.Equal(hits, []string{"/2026-04-25-17.json.gz"}) {
		t.Fatalf("hits = %v, want only missing hour", hits)
	}
}

func TestDownloadMissingHoursReturnsHTTPError(t *testing.T) {
	dir := t.TempDir()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer srv.Close()

	err := DownloadMissingHours(DownloadOptions{
		BaseURL:     srv.URL,
		TargetDate:  "2026-04-25",
		SourceDir:   dir,
		Hours:       []int{16},
		Timeout:     5 * time.Second,
		MaxParallel: 1,
	})
	if err == nil {
		t.Fatal("expected download error, got nil")
	}

	if _, statErr := os.Stat(filepath.Join(dir, "2026-04-25-16.json.gz")); !os.IsNotExist(statErr) {
		t.Fatalf("expected no downloaded file on error, stat err = %v", statErr)
	}
}
