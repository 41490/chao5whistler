use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MinuteOffsetsIndex {
    pub schema_version: String,
    pub source_day: String,
    pub generated_at_utc: String,
    pub hours: Vec<HourMinuteIndex>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct HourMinuteIndex {
    pub source_day: String,
    pub hour: u8,
    pub normalized_relative_path: String,
    pub minute_offsets: Vec<MinuteOffsetRecord>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MinuteOffsetRecord {
    pub minute: u8,
    pub second_of_day_start: u32,
    pub event_index_offset: u64,
    pub uncompressed_byte_offset: u64,
    pub event_count: u64,
}
