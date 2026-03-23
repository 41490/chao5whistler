use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use super::normalized_event::NormalizedEvent;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeEventSource {
    ArchiveReplay,
    FallbackSynthetic,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RuntimeEvent {
    pub source: RuntimeEventSource,
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

impl From<&NormalizedEvent> for RuntimeEvent {
    fn from(value: &NormalizedEvent) -> Self {
        Self {
            source: RuntimeEventSource::ArchiveReplay,
            event_id: value.event_id.clone(),
            source_day: value.source_day.clone(),
            source_hour: value.source_hour,
            created_at_utc: value.created_at_utc.clone(),
            second_of_day: value.second_of_day,
            event_type: value.event_type.clone(),
            weight: value.weight,
            repo_full_name: value.repo_full_name.clone(),
            actor_login: value.actor_login.clone(),
            display_hash: value.display_hash.clone(),
            text_fields: value.text_fields.clone(),
            audio_class: value.audio_class.clone(),
            visual_class: value.visual_class.clone(),
            raw_ref: value.raw_ref.clone(),
        }
    }
}
