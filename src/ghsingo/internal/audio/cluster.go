package audio

import "sort"

// EventEntry is the minimal per-event info needed for clustering.
type EventEntry struct {
	TypeID uint8
	Weight uint8
}

// Source selects between pre-rendered sample playback and runtime synth.
type Source uint8

const (
	// SourceSample plays a pre-rendered long-form WAV (rank 1 + Release).
	SourceSample Source = 0
	// SourceSynth plays a Karplus-Strong runtime synth (rank 2-4).
	SourceSynth Source = 1
)

// NoteTrigger is a scheduled bell strike derived from a GH event.
type NoteTrigger struct {
	Pitch     Pitch
	Velocity  float32
	MsOffset  int // 0~SpreadMs within the current second
	Source    Source
	TypeID    uint8 // origin event type, useful for video/log
	WithOcean bool  // true only for ReleaseEvent (adds ocean sample)
}

// ClusterConfig governs the per-second event-to-note mapping.
type ClusterConfig struct {
	KeepTopN        int        // top-N event types by count to keep (typically 4)
	EventTypeIDs    []uint8    // event TypeIDs eligible for ranking
	AlwaysFireIDs   []uint8    // event TypeIDs that always trigger (e.g. Release)
	Velocities      [4]float32 // velocity per rank (rank 1..4)
	ReleaseVelocity float32    // velocity for always-fire events
	OctaveRank1     Octave
	OctaveRank2     []Octave // cycled across repeated rank-2 events
	OctaveRank3     Octave
	OctaveRank4     Octave
	OctaveRelease   Octave
	SpreadMs        int // total ms window (default 500); triggers spaced evenly
}

var rankNotes = [4]Note{NoteGong, NoteShang, NoteJue, NoteZhi}

// Assign converts a list of one-second events (in original order) into
// scheduled NoteTriggers. Events not in EventTypeIDs or AlwaysFireIDs are
// dropped. Ranked events get notes by their type's rank; AlwaysFire events
// always produce NoteYu at OctaveRelease with WithOcean=true.
func Assign(events []EventEntry, cfg ClusterConfig) []NoteTrigger {
	if len(events) == 0 {
		return nil
	}
	rankable := map[uint8]bool{}
	for _, id := range cfg.EventTypeIDs {
		rankable[id] = true
	}
	always := map[uint8]bool{}
	for _, id := range cfg.AlwaysFireIDs {
		always[id] = true
	}

	counts := map[uint8]int{}
	firstSeen := map[uint8]int{}
	for i, ev := range events {
		if rankable[ev.TypeID] {
			if _, ok := firstSeen[ev.TypeID]; !ok {
				firstSeen[ev.TypeID] = i
			}
			counts[ev.TypeID]++
		}
	}

	type pair struct {
		typeID uint8
		count  int
		first  int
	}
	sorted := make([]pair, 0, len(counts))
	for id, c := range counts {
		sorted = append(sorted, pair{id, c, firstSeen[id]})
	}
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].count != sorted[j].count {
			return sorted[i].count > sorted[j].count
		}
		// tie-break: earlier first-seen wins (preserves event order)
		return sorted[i].first < sorted[j].first
	})
	if len(sorted) > cfg.KeepTopN {
		sorted = sorted[:cfg.KeepTopN]
	}
	rankOf := map[uint8]int{}
	for idx, p := range sorted {
		rankOf[p.typeID] = idx // 0..3
	}

	rank2Seen := 0

	triggers := make([]NoteTrigger, 0, len(events))
	for _, ev := range events {
		switch {
		case always[ev.TypeID]:
			triggers = append(triggers, NoteTrigger{
				Pitch:     Pitch{Note: NoteYu, Octave: cfg.OctaveRelease},
				Velocity:  cfg.ReleaseVelocity,
				Source:    SourceSample,
				TypeID:    ev.TypeID,
				WithOcean: true,
			})
		case rankable[ev.TypeID]:
			r, ok := rankOf[ev.TypeID]
			if !ok {
				continue
			}
			var octave Octave
			var source Source
			switch r {
			case 0:
				octave = cfg.OctaveRank1
				source = SourceSample
			case 1:
				if len(cfg.OctaveRank2) == 0 {
					octave = OctaveMid
				} else {
					octave = cfg.OctaveRank2[rank2Seen%len(cfg.OctaveRank2)]
				}
				rank2Seen++
				source = SourceSynth
			case 2:
				octave = cfg.OctaveRank3
				source = SourceSynth
			case 3:
				octave = cfg.OctaveRank4
				source = SourceSynth
			}
			triggers = append(triggers, NoteTrigger{
				Pitch:    Pitch{Note: rankNotes[r], Octave: octave},
				Velocity: cfg.Velocities[r],
				Source:   source,
				TypeID:   ev.TypeID,
			})
		}
	}

	spread := cfg.SpreadMs
	if spread <= 0 {
		spread = 500
	}
	n := len(triggers)
	if n > 0 {
		step := spread / n
		for i := range triggers {
			triggers[i].MsOffset = i * step
		}
	}
	return triggers
}
