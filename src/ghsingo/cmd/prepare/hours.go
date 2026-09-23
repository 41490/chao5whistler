package main

import (
	"fmt"
	"slices"
	"strconv"
	"strings"
)

func parseHours(spec string) ([]int, error) {
	if strings.TrimSpace(spec) == "" {
		hours := make([]int, 24)
		for h := range 24 {
			hours[h] = h
		}
		return hours, nil
	}

	seen := make(map[int]struct{}, 24)
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			return nil, fmt.Errorf("invalid empty hour token in %q", spec)
		}
		if strings.Contains(part, "-") {
			bounds := strings.Split(part, "-")
			if len(bounds) != 2 {
				return nil, fmt.Errorf("invalid hour range %q", part)
			}
			start, err := parseHour(bounds[0])
			if err != nil {
				return nil, err
			}
			end, err := parseHour(bounds[1])
			if err != nil {
				return nil, err
			}
			if end < start {
				return nil, fmt.Errorf("invalid descending hour range %q", part)
			}
			for hour := start; hour <= end; hour++ {
				seen[hour] = struct{}{}
			}
			continue
		}
		hour, err := parseHour(part)
		if err != nil {
			return nil, err
		}
		seen[hour] = struct{}{}
	}

	hours := make([]int, 0, len(seen))
	for hour := range seen {
		hours = append(hours, hour)
	}
	slices.Sort(hours)
	return hours, nil
}

func parseHour(s string) (int, error) {
	hour, err := strconv.Atoi(strings.TrimSpace(s))
	if err != nil {
		return 0, fmt.Errorf("invalid hour %q", s)
	}
	if hour < 0 || hour > 23 {
		return 0, fmt.Errorf("hour %d out of range [0,23]", hour)
	}
	return hour, nil
}
