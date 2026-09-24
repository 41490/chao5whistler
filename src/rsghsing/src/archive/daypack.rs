//! GSIN day-pack binary format.
//!
//! Normative reference: `src/ghsingo/internal/archive/daypack.go`.
//! Layout (little-endian):
//!   header 16B = magic "GSIN" | version u16 | date u32 (YYYYMMDD)
//!              | total_ticks u32 | reserved 2B
//!   then `total_ticks` slots, each: count u8, then `count` events of
//!   type_id u8 | weight u8 | text_len u8 | text bytes.

use std::fs;
use std::io;
use std::path::Path;

use thiserror::Error;

pub const HEADER_SIZE: usize = 16;
pub const MAX_EVENTS_PER_TICK: usize = 4;
pub const MAX_TEXT_LEN: usize = 64;
pub const TOTAL_TICKS: usize = 86_400;
pub const VERSION: u16 = 1;

#[derive(Debug, Error)]
pub enum DaypackError {
    #[error("bad magic: got {got:?}, want \"GSIN\"")]
    BadMagic { got: [u8; 4] },
    #[error("bad version: got {got}, want {want}")]
    BadVersion { got: u16, want: u16 },
    #[error("bad total_ticks: got {got}, want {TOTAL_TICKS}")]
    BadTotalTicks { got: u32 },
    #[error("tick {tick}: event count {n} exceeds max {MAX_EVENTS_PER_TICK}")]
    TooManyEvents { tick: usize, n: usize },
    #[error("tick {tick}: truncated at {where_}")]
    Truncated { tick: usize, where_: &'static str },
    #[error("trailing bytes after {TOTAL_TICKS} ticks: {extra}")]
    TrailingBytes { extra: usize },
    #[error(transparent)]
    Io(#[from] io::Error),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Event {
    pub type_id: u8,
    pub weight: u8,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Tick {
    pub events: Vec<Event>,
}

#[derive(Debug, Clone)]
pub struct Daypack {
    pub version: u16,
    pub date: u32,
    pub ticks: Vec<Tick>,
}

/// Truncates to at most `max_bytes` bytes without splitting a UTF-8 char.
/// Same result as Go `truncateUTF8`.
pub fn truncate_utf8(s: &str, max_bytes: usize) -> &str {
    if s.len() <= max_bytes {
        return s;
    }
    let mut n = max_bytes;
    while n > 0 && !s.is_char_boundary(n) {
        n -= 1;
    }
    &s[..n]
}

impl Daypack {
    pub fn new(date: u32, ticks: Vec<Tick>) -> Self {
        Self {
            version: VERSION,
            date,
            ticks,
        }
    }

    pub fn write(&self, path: &Path) -> Result<(), DaypackError> {
        let mut buf = Vec::with_capacity(HEADER_SIZE + TOTAL_TICKS * (MAX_EVENTS_PER_TICK + 1));
        buf.extend_from_slice(b"GSIN");
        buf.extend_from_slice(&self.version.to_le_bytes());
        buf.extend_from_slice(&self.date.to_le_bytes());
        buf.extend_from_slice(&(TOTAL_TICKS as u32).to_le_bytes());
        buf.extend_from_slice(&[0, 0]); // reserved

        for tick in 0..TOTAL_TICKS {
            let events = self
                .ticks
                .get(tick)
                .map(|t| t.events.as_slice())
                .unwrap_or(&[]);
            let n = events.len().min(MAX_EVENTS_PER_TICK);
            buf.push(n as u8);
            for ev in &events[..n] {
                let text = truncate_utf8(&ev.text, MAX_TEXT_LEN).as_bytes();
                buf.push(ev.type_id);
                buf.push(ev.weight);
                buf.push(text.len() as u8);
                buf.extend_from_slice(text);
            }
        }
        fs::write(path, &buf)?;
        Ok(())
    }

    pub fn read(path: &Path) -> Result<Daypack, DaypackError> {
        let buf = fs::read(path)?;
        Self::from_bytes(&buf)
    }

    pub fn from_bytes(buf: &[u8]) -> Result<Daypack, DaypackError> {
        let mut cur = Cursor::new(buf);
        let magic = cur.take(4, "magic")?;
        if magic != b"GSIN" {
            return Err(DaypackError::BadMagic {
                got: [magic[0], magic[1], magic[2], magic[3]],
            });
        }
        let version = cur.u16("version")?;
        if version != VERSION {
            return Err(DaypackError::BadVersion {
                got: version,
                want: VERSION,
            });
        }
        let date = cur.u32("date")?;
        let total_ticks = cur.u32("total_ticks")?;
        if total_ticks as usize != TOTAL_TICKS {
            return Err(DaypackError::BadTotalTicks { got: total_ticks });
        }
        let _reserved = cur.take(2, "reserved")?;

        let mut ticks = Vec::with_capacity(TOTAL_TICKS);
        for tick in 0..TOTAL_TICKS {
            let n = cur.take(1, "count")?[0] as usize;
            if n > MAX_EVENTS_PER_TICK {
                return Err(DaypackError::TooManyEvents { tick, n });
            }
            let mut events = Vec::with_capacity(n);
            for _ in 0..n {
                let meta = cur.take(3, "event meta")?;
                let tl = meta[2] as usize;
                let text = cur.take(tl, "event text")?;
                events.push(Event {
                    type_id: meta[0],
                    weight: meta[1],
                    text: String::from_utf8_lossy(text).into_owned(),
                });
            }
            ticks.push(Tick { events });
        }
        if cur.pos != buf.len() {
            return Err(DaypackError::TrailingBytes {
                extra: buf.len() - cur.pos,
            });
        }
        Ok(Daypack {
            version,
            date,
            ticks,
        })
    }
}

struct Cursor<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> Cursor<'a> {
    fn new(buf: &'a [u8]) -> Self {
        Self { buf, pos: 0 }
    }

    fn take(&mut self, n: usize, where_: &'static str) -> Result<&'a [u8], DaypackError> {
        let end = self.pos + n;
        if end > self.buf.len() {
            return Err(DaypackError::Truncated {
                tick: self.pos,
                where_,
            });
        }
        let out = &self.buf[self.pos..end];
        self.pos = end;
        Ok(out)
    }

    fn u16(&mut self, where_: &'static str) -> Result<u16, DaypackError> {
        Ok(u16::from_le_bytes(
            self.take(2, where_)?.try_into().unwrap(),
        ))
    }

    fn u32(&mut self, where_: &'static str) -> Result<u32, DaypackError> {
        Ok(u32::from_le_bytes(
            self.take(4, where_)?.try_into().unwrap(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ev(type_id: u8, weight: u8, text: &str) -> Event {
        Event {
            type_id,
            weight,
            text: text.to_string(),
        }
    }

    #[test]
    fn truncate_utf8_never_splits_a_char() {
        assert_eq!(truncate_utf8("short", 64), "short");
        assert_eq!(truncate_utf8("abcdef", 3), "abc");
        // "a" + "é"(2B) + "中"(3B) + "文"(3B): cuts at 4 and 5 land inside 中.
        assert_eq!(truncate_utf8("aé中文", 4), "aé");
        assert_eq!(truncate_utf8("aé中文", 5), "aé");
        assert_eq!(truncate_utf8("aé中文", 6), "aé中");
    }

    #[test]
    fn write_then_read_roundtrips() {
        let mut ticks = vec![Tick::default(); TOTAL_TICKS];
        ticks[0].events = vec![ev(0, 255, "a/b"), ev(5, 100, "")];
        ticks[86_399].events = vec![ev(3, 77, "x/y")];
        let pack = Daypack::new(2026_0328, ticks.clone());

        let dir = std::env::temp_dir().join("rsghsing-daypack-roundtrip");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("day.bin");
        pack.write(&path).unwrap();

        let back = Daypack::read(&path).unwrap();
        assert_eq!(back.version, VERSION);
        assert_eq!(back.date, 2026_0328);
        assert_eq!(back.ticks.len(), TOTAL_TICKS);
        assert_eq!(back.ticks[0].events, ticks[0].events);
        assert_eq!(back.ticks[86_399].events, ticks[86_399].events);
        assert!(back.ticks[1].events.is_empty());
    }

    #[test]
    fn header_is_16_bytes_little_endian() {
        let pack = Daypack::new(2026_0328, Vec::new());
        let dir = std::env::temp_dir().join("rsghsing-daypack-header");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("day.bin");
        pack.write(&path).unwrap();
        let buf = std::fs::read(&path).unwrap();

        assert_eq!(&buf[0..4], b"GSIN");
        assert_eq!(u16::from_le_bytes([buf[4], buf[5]]), 1);
        assert_eq!(
            u32::from_le_bytes(buf[6..10].try_into().unwrap()),
            2026_0328
        );
        assert_eq!(u32::from_le_bytes(buf[10..14].try_into().unwrap()), 86_400);
        assert_eq!(&buf[14..16], &[0, 0]);
        // Empty ticks still cost one count byte each.
        assert_eq!(buf.len(), HEADER_SIZE + TOTAL_TICKS);
    }

    #[test]
    fn text_longer_than_64_bytes_is_truncated_on_write() {
        let long = "z".repeat(200);
        let mut ticks = vec![Tick::default(); TOTAL_TICKS];
        ticks[7].events = vec![ev(1, 9, &long)];
        let pack = Daypack::new(2026_0328, ticks);

        let dir = std::env::temp_dir().join("rsghsing-daypack-trunc");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("day.bin");
        pack.write(&path).unwrap();
        let back = Daypack::read(&path).unwrap();
        assert_eq!(back.ticks[7].events[0].text.len(), MAX_TEXT_LEN);
    }

    #[test]
    fn read_rejects_bad_magic_and_bad_counts() {
        let mut buf = vec![0u8; HEADER_SIZE + TOTAL_TICKS];
        buf[0..4].copy_from_slice(b"XXXX");
        assert!(matches!(
            Daypack::from_bytes(&buf),
            Err(DaypackError::BadMagic { .. })
        ));

        let mut buf = vec![0u8; HEADER_SIZE + TOTAL_TICKS];
        buf[0..4].copy_from_slice(b"GSIN");
        buf[4..6].copy_from_slice(&1u16.to_le_bytes());
        buf[10..14].copy_from_slice(&(TOTAL_TICKS as u32).to_le_bytes());
        buf[HEADER_SIZE] = 9; // > MAX_EVENTS_PER_TICK
        assert!(matches!(
            Daypack::from_bytes(&buf),
            Err(DaypackError::TooManyEvents { tick: 0, n: 9 })
        ));
    }
}
