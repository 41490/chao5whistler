package archive

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type DownloadOptions struct {
	BaseURL     string
	TargetDate  string
	SourceDir   string
	Hours       []int
	Timeout     time.Duration
	MaxParallel int
	UserAgent   string
}

func HourFilePath(sourceDir, targetDate string, hour int) string {
	return filepath.Join(sourceDir, fmt.Sprintf("%s-%d.json.gz", targetDate, hour))
}

func DownloadMissingHours(opts DownloadOptions) error {
	if err := os.MkdirAll(opts.SourceDir, 0755); err != nil {
		return fmt.Errorf("mkdir source dir: %w", err)
	}

	missing := make([]int, 0, len(opts.Hours))
	for _, hour := range opts.Hours {
		if _, err := os.Stat(HourFilePath(opts.SourceDir, opts.TargetDate, hour)); err == nil {
			continue
		} else if !os.IsNotExist(err) {
			return fmt.Errorf("stat source hour %d: %w", hour, err)
		}
		missing = append(missing, hour)
	}
	if len(missing) == 0 {
		return nil
	}

	timeout := opts.Timeout
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	maxParallel := opts.MaxParallel
	if maxParallel <= 0 {
		maxParallel = 1
	}

	client := &http.Client{Timeout: timeout}
	var wg sync.WaitGroup
	errCh := make(chan error, len(missing))
	sem := make(chan struct{}, maxParallel)

	for _, hour := range missing {
		wg.Add(1)
		sem <- struct{}{}
		go func(hour int) {
			defer wg.Done()
			defer func() { <-sem }()
			if err := downloadHour(client, opts, hour); err != nil {
				errCh <- err
			}
		}(hour)
	}

	wg.Wait()
	close(errCh)

	for err := range errCh {
		if err != nil {
			return err
		}
	}
	return nil
}

func downloadHour(client *http.Client, opts DownloadOptions, hour int) error {
	url := fmt.Sprintf("%s/%s-%d.json.gz", strings.TrimRight(opts.BaseURL, "/"), opts.TargetDate, hour)
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return fmt.Errorf("build request %s: %w", url, err)
	}
	if opts.UserAgent != "" {
		req.Header.Set("User-Agent", opts.UserAgent)
	}

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("download %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download %s: unexpected status %s", url, resp.Status)
	}

	path := HourFilePath(opts.SourceDir, opts.TargetDate, hour)
	tmpPath := path + ".part"
	f, err := os.Create(tmpPath)
	if err != nil {
		return fmt.Errorf("create %s: %w", tmpPath, err)
	}
	if _, err := io.Copy(f, resp.Body); err != nil {
		f.Close()
		_ = os.Remove(tmpPath)
		return fmt.Errorf("write %s: %w", tmpPath, err)
	}
	if err := f.Close(); err != nil {
		_ = os.Remove(tmpPath)
		return fmt.Errorf("close %s: %w", tmpPath, err)
	}
	if err := os.Rename(tmpPath, path); err != nil {
		_ = os.Remove(tmpPath)
		return fmt.Errorf("rename %s -> %s: %w", tmpPath, path, err)
	}
	return nil
}
