package audio

import (
	"math/rand"
	"sort"
)

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

	// Conductor mode (added 2026-04-25): when true, emit one prominent "lead
	// bell" per data-second representing the rank-1 event type, and drop all
	// other events to a quiet ambient background bed. When false, the legacy
	// "every event becomes a bell" behavior applies.
	ConductorMode      bool
	LeadVelocity       float32 // velocity for the single lead bell (e.g. 1.00)
	BackgroundVelocity float32 // multiplier on rank velocities for background events (e.g. 0.18)
	WindowMs           int     // active window length in ms within each second (e.g. 800)
	WindowJitterMs     int     // random window-start jitter in ms 0..N (e.g. 200)
}

var rankNotes = [4]Note{NoteGong, NoteShang, NoteJue, NoteZhi}

// Assign converts a list of one-second events (in original order) into
// scheduled NoteTriggers. The algorithm depends on ClusterConfig.ConductorMode:
//
//	ConductorMode == false (legacy): every event produces a NoteTrigger ranked
//	by its type's count; rank 1 + AlwaysFire types use SourceSample, rank 2-4
//	use SourceSynth.
//
//	ConductorMode == true: emit at most ONE "lead bell" representing the
//	rank-1 type at full velocity, with all other event instances becoming a
//	quiet background bed (synth voices at BackgroundVelocity * rank velocity).
func Assign(events []EventEntry, cfg ClusterConfig) []NoteTrigger {
	if len(events) == 0 {
		return nil
	}
	if cfg.ConductorMode {
		return assignConductor(events, cfg)
	}
	return assignLegacy(events, cfg)
}

// assignLegacy is the original "every event becomes a bell" algorithm. Events
// not in EventTypeIDs or AlwaysFireIDs are dropped. Ranked events get notes
// by their type's rank; AlwaysFire events always produce NoteYu at
// OctaveRelease with WithOcean=true.
func assignLegacy(events []EventEntry, cfg ClusterConfig) []NoteTrigger {
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

// assignConductor implements the per-second "one lead bell + quiet bed" algorithm.
//
//  1. Filter to known types (rankable + always-fire combined).
//  2. Count per type; rank by count (tie-break: first-seen).
//  3. Lead = rank-1 type. Fires ONCE as the first occurrence of that type
//     in the input order, at full LeadVelocity, Source=SourceSample.
//     If lead is in AlwaysFireIDs, the trigger carries WithOcean=true and
//     uses NoteYu @ OctaveRelease (the AlwaysFire treatment).
//  4. All OTHER event instances become background: legacy rank logic for
//     note/octave, but Source=SourceSynth, Velocity scaled by BackgroundVelocity,
//     WithOcean=false.
//  5. Window: random offset 0..WindowJitterMs at start, total length WindowMs.
//     Lead fires at window start; background events spread evenly within window.
func assignConductor(events []EventEntry, cfg ClusterConfig) []NoteTrigger {
	// 1. Filter known types.
	rankable := map[uint8]bool{}
	for _, id := range cfg.EventTypeIDs {
		rankable[id] = true
	}
	always := map[uint8]bool{}
	for _, id := range cfg.AlwaysFireIDs {
		always[id] = true
	}
	known := func(id uint8) bool { return rankable[id] || always[id] }

	filtered := make([]EventEntry, 0, len(events))
	for _, ev := range events {
		if known(ev.TypeID) {
			filtered = append(filtered, ev)
		}
	}
	if len(filtered) == 0 {
		return nil
	}

	// 2. Count per type, rank by count (first-seen tie-break).
	counts := map[uint8]int{}
	firstSeen := map[uint8]int{}
	for i, ev := range filtered {
		if _, ok := firstSeen[ev.TypeID]; !ok {
			firstSeen[ev.TypeID] = i
		}
		counts[ev.TypeID]++
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
		return sorted[i].first < sorted[j].first
	})
	if cfg.KeepTopN > 0 && len(sorted) > cfg.KeepTopN {
		sorted = sorted[:cfg.KeepTopN]
	}
	rankOf := map[uint8]int{}
	for idx, p := range sorted {
		rankOf[p.typeID] = idx
	}
	leadType := sorted[0].typeID
	leadIdx := firstSeen[leadType]

	// 3. Window timing.
	windowStart := 0
	if cfg.WindowJitterMs > 0 {
		windowStart = rand.Intn(cfg.WindowJitterMs + 1)
	}
	windowMs := cfg.WindowMs
	if windowMs <= 0 {
		windowMs = 800
	}

	// 4. Background events = filtered minus the lead instance.
	bgEvents := make([]EventEntry, 0, len(filtered)-1)
	for i, ev := range filtered {
		if i == leadIdx {
			continue
		}
		bgEvents = append(bgEvents, ev)
	}

	// 5. Build triggers.
	triggers := make([]NoteTrigger, 0, len(filtered))

	// Lead bell.
	leadTrigger := NoteTrigger{
		Velocity: cfg.LeadVelocity,
		Source:   SourceSample,
		TypeID:   leadType,
		MsOffset: windowStart,
	}
	if always[leadType] {
		leadTrigger.Pitch = Pitch{Note: NoteYu, Octave: cfg.OctaveRelease}
		leadTrigger.WithOcean = true
	} else {
		leadTrigger.Pitch = Pitch{Note: rankNotes[0], Octave: cfg.OctaveRank1}
	}
	triggers = append(triggers, leadTrigger)

	// Background bed: evenly spread within window.
	rank2Seen := 0
	for i, ev := range bgEvents {
		var note Note
		var octave Octave
		var rankVel float32

		if always[ev.TypeID] {
			// Background instance of an AlwaysFire type: still NoteYu but
			// without ocean, treated as rank-Release register but quiet.
			note = NoteYu
			octave = cfg.OctaveRelease
			rankVel = cfg.ReleaseVelocity
		} else {
			r, ok := rankOf[ev.TypeID]
			if !ok {
				continue // truncated by KeepTopN
			}
			note = rankNotes[r]
			rankVel = cfg.Velocities[r]
			switch r {
			case 0:
				octave = cfg.OctaveRank1
			case 1:
				if len(cfg.OctaveRank2) == 0 {
					octave = OctaveMid
				} else {
					octave = cfg.OctaveRank2[rank2Seen%len(cfg.OctaveRank2)]
				}
				rank2Seen++
			case 2:
				octave = cfg.OctaveRank3
			case 3:
				octave = cfg.OctaveRank4
			}
		}

		offset := windowStart + windowMs*(i+1)/(len(bgEvents)+1)
		triggers = append(triggers, NoteTrigger{
			Pitch:    Pitch{Note: note, Octave: octave},
			Velocity: rankVel * cfg.BackgroundVelocity,
			Source:   SourceSynth,
			TypeID:   ev.TypeID,
			MsOffset: offset,
		})
	}

	return triggers
}
