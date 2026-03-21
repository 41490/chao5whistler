use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct NormalizedEvent {
    pub event_id: String,
    pub source_day: String,
    pub source_hour: u8,
    pub created_at_utc: String,
    pub second_of_day: u32,
    pub event_type: String,
    pub weight: u8,
    pub repo_full_name: String,
    pub actor_login: String,
    pub display_hash: String,
    pub text_fields: BTreeMap<String, String>,
    pub audio_class: String,
    pub visual_class: String,
    pub raw_ref: String,
}
