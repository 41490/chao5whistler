//! 五声 pitch grid. Ported from `internal/audio/pitch.go`.

/// 宫商角徵羽.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Note {
    Gong,
    Shang,
    Jue,
    Zhi,
    Yu,
}

pub const NOTE_COUNT: usize = 5;

/// Octave bands: low = C3..A3, mid = C4..A4, high = C5..A5.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Octave {
    Low,
    Mid,
    High,
}

pub const OCTAVE_COUNT: usize = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Pitch {
    pub note: Note,
    pub octave: Octave,
}

const BASE_FREQ: [f64; NOTE_COUNT] = [
    130.81, // C3 宫
    146.83, // D3 商
    164.81, // E3 角
    196.00, // G3 徵
    220.00, // A3 羽
];

impl Note {
    pub fn letter(self) -> &'static str {
        ["C", "D", "E", "G", "A"][self as usize]
    }
    pub fn index(self) -> usize {
        self as usize
    }
}

impl Octave {
    pub fn number(self) -> i32 {
        self as i32 + 3
    }
}

impl Pitch {
    pub fn frequency(self) -> f64 {
        let base = BASE_FREQ[self.note.index()];
        match self.octave {
            Octave::Low => base,
            Octave::Mid => base * 2.0,
            Octave::High => base * 4.0,
        }
    }

    pub fn filename(self) -> String {
        format!("{}{}.wav", self.note.letter(), self.octave.number())
    }
}

/// All 15 pitches in (octave, note) order — mirrors `AllPitches`.
pub fn all_pitches() -> Vec<Pitch> {
    let mut out = Vec::with_capacity(NOTE_COUNT * OCTAVE_COUNT);
    for o in [Octave::Low, Octave::Mid, Octave::High] {
        for n in [Note::Gong, Note::Shang, Note::Jue, Note::Zhi, Note::Yu] {
            out.push(Pitch { note: n, octave: o });
        }
    }
    out
}

/// notePan: 宫 centre, 商 left, 角 right, 徵 far left, 羽 far right.
pub fn note_pan(n: Note) -> f32 {
    [0.50, 0.35, 0.65, 0.25, 0.75][n.index()]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frequencies_match_go_table() {
        assert_eq!(Pitch { note: Note::Gong, octave: Octave::Low }.frequency(), 130.81);
        assert_eq!(Pitch { note: Note::Gong, octave: Octave::Mid }.frequency(), 261.62);
        assert_eq!(Pitch { note: Note::Yu, octave: Octave::High }.frequency(), 880.0);
        assert_eq!(all_pitches().len(), 15);
        assert_eq!(all_pitches()[0].filename(), "C3.wav");
        assert_eq!(all_pitches()[14].filename(), "A5.wav");
    }
}
