use std::collections::BTreeMap;

use anyhow::Result;
use chrono::{DateTime, Timelike};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::config::schema::EventType;
use crate::model::normalized_event::NormalizedEvent;

pub fn normalize_event(
    value: &Value,
    day: &str,
    hour: u8,
    line_number: u64,
    weights: &BTreeMap<String, u8>,
    hash_len_default: usize,
) -> Result<Option<NormalizedEvent>> {
    let event_type = string_field(value, "type").unwrap_or_default();
    let Some(weight) = weights.get(&event_type).copied() else {
        return Ok(None);
    };

    let event_id = string_field(value, "id")
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| format!("{day}-{hour:02}-{line_number:06}"));
    let created_at = string_field(value, "created_at")
        .ok_or_else(|| anyhow::anyhow!("missing created_at for event {}", event_id))?;
    let created_at = DateTime::parse_from_rfc3339(&created_at)?;
    let second_of_day = created_at.hour() * 3600 + created_at.minute() * 60 + created_at.second();
    let repo_full_name = value
        .get("repo")
        .and_then(|repo| repo.get("name"))
        .and_then(Value::as_str)
        .unwrap_or("unknown/unknown")
        .to_string();
    let actor_login = value
        .get("actor")
        .and_then(|actor| actor.get("login"))
        .and_then(Value::as_str)
        .unwrap_or("ghost")
        .to_string();
    let display_hash = display_hash(value, &event_type, &event_id, hash_len_default);

    let mut text_fields = BTreeMap::new();
    text_fields.insert("repo".to_string(), repo_full_name.clone());
    text_fields.insert(
        "repo_owner".to_string(),
        repo_full_name
            .split('/')
            .next()
            .unwrap_or_default()
            .to_string(),
    );
    text_fields.insert(
        "repo_name".to_string(),
        repo_full_name
            .split('/')
            .nth(1)
            .unwrap_or_default()
            .to_string(),
    );
    text_fields.insert("type".to_string(), event_type.clone());
    text_fields.insert("actor".to_string(), actor_login.clone());
    text_fields.insert("hash".to_string(), display_hash.clone());
    text_fields.insert("id".to_string(), event_id.clone());
    text_fields.insert("weight".to_string(), weight.to_string());
    text_fields.insert("hour".to_string(), format!("{hour:02}"));
    text_fields.insert("minute".to_string(), format!("{:02}", created_at.minute()));
    text_fields.insert("second".to_string(), format!("{:02}", created_at.second()));

    Ok(Some(NormalizedEvent {
        event_id,
        source_day: day.to_string(),
        source_hour: hour,
        created_at_utc: created_at.to_rfc3339(),
        second_of_day,
        event_type: event_type.clone(),
        weight,
        repo_full_name,
        actor_login,
        display_hash,
        text_fields,
        audio_class: event_type.clone(),
        visual_class: event_type,
        raw_ref: format!("{day}/raw/{hour:02}.json.gz#line:{line_number}"),
    }))
}

pub fn build_fixture_primary_event(day: &str, hour: u8, event_type: EventType) -> Value {
    let repo = format!("fixture/{:02}-{}", hour, event_type.as_str().to_lowercase());
    let actor = format!("fixture_actor_{hour:02}");
    let created_at = format!("{day}T{hour:02}:12:34Z");
    let id = format!("{day}-{hour:02}-primary");
    match event_type {
        EventType::CreateEvent => json!({
            "id": id,
            "type": "CreateEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"ref_type": "branch", "ref": format!("feature-{hour:02}")},
        }),
        EventType::DeleteEvent => json!({
            "id": id,
            "type": "DeleteEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"ref_type": "tag", "ref": format!("v1.{hour}")},
        }),
        EventType::PushEvent => json!({
            "id": id,
            "type": "PushEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {
                "head": format!("{hour:02}aa11bb22cc33dd44ee55ff66778899aa00bb11"),
                "commits": [{"sha": format!("{hour:02}ff11bb22cc33dd44ee55ff66778899aa00bb77")}]
            },
        }),
        EventType::IssuesEvent => json!({
            "id": id,
            "type": "IssuesEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"issue": {"id": 1000 + hour as u64}},
        }),
        EventType::IssueCommentEvent => json!({
            "id": id,
            "type": "IssueCommentEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"comment": {"id": 2000 + hour as u64}},
        }),
        EventType::CommitCommentEvent => json!({
            "id": id,
            "type": "CommitCommentEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"comment": {"id": 3000 + hour as u64, "commit_id": format!("commit-{hour:02}")}},
        }),
        EventType::PullRequestEvent => json!({
            "id": id,
            "type": "PullRequestEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"pull_request": {"id": 4000 + hour as u64, "head": {"sha": format!("{hour:02}99887766554433221100aabbccddeeff001122")}}},
        }),
        EventType::PublicEvent => json!({
            "id": id,
            "type": "PublicEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"repository_id": 5000 + hour as u64},
        }),
        EventType::ForkEvent => json!({
            "id": id,
            "type": "ForkEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"forkee": {"id": 6000 + hour as u64}},
        }),
        EventType::ReleaseEvent => json!({
            "id": id,
            "type": "ReleaseEvent",
            "created_at": created_at,
            "repo": {"name": repo},
            "actor": {"login": actor},
            "payload": {"release": {"id": 7000 + hour as u64}},
        }),
    }
}

pub fn build_fixture_secondary_event(day: &str, hour: u8) -> Value {
    json!({
        "id": format!("{day}-{hour:02}-secondary"),
        "type": "WatchEvent",
        "created_at": format!("{day}T{hour:02}:45:00Z"),
        "repo": {"name": format!("fixture/{hour:02}-watch")},
        "actor": {"login": format!("watch_actor_{hour:02}")},
        "payload": {"action": "started"},
    })
}

fn display_hash(value: &Value, event_type: &str, event_id: &str, width: usize) -> String {
    let width = width.clamp(4, 16);
    let payload = value.get("payload").unwrap_or(&Value::Null);
    let raw = match event_type {
        "PushEvent" => payload
            .get("head")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or_else(|| {
                payload
                    .get("commits")
                    .and_then(Value::as_array)
                    .and_then(|commits| commits.first())
                    .and_then(|commit| commit.get("sha"))
                    .and_then(Value::as_str)
                    .map(ToOwned::to_owned)
            }),
        "PullRequestEvent" => payload
            .get("pull_request")
            .and_then(|pr| pr.get("head"))
            .and_then(|head| head.get("sha"))
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or_else(|| derived_payload_id(payload, "pull_request", "id")),
        "CreateEvent" | "DeleteEvent" => Some(format!(
            "{}:{}:{}",
            payload
                .get("ref_type")
                .and_then(Value::as_str)
                .unwrap_or("ref"),
            payload
                .get("ref")
                .and_then(Value::as_str)
                .unwrap_or("unknown"),
            event_id
        )),
        "IssuesEvent" => derived_payload_id(payload, "issue", "id"),
        "IssueCommentEvent" => derived_payload_id(payload, "comment", "id"),
        "CommitCommentEvent" => payload
            .get("comment")
            .and_then(|comment| comment.get("commit_id"))
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or_else(|| derived_payload_id(payload, "comment", "id")),
        "PublicEvent" => payload
            .get("repository_id")
            .map(value_to_string)
            .filter(|value| !value.is_empty()),
        "ForkEvent" => derived_payload_id(payload, "forkee", "id"),
        "ReleaseEvent" => derived_payload_id(payload, "release", "id"),
        other => Some(format!("{other}:{event_id}")),
    };

    let raw = raw.unwrap_or_else(|| event_id.to_string());
    let canonical = raw.replace('-', "");
    if canonical.len() >= width && canonical.chars().all(|ch| ch.is_ascii_hexdigit()) {
        canonical[..width].to_string()
    } else {
        short_digest(&format!("{event_type}:{raw}:{event_id}"), width)
    }
}

fn derived_payload_id(payload: &Value, object_key: &str, id_key: &str) -> Option<String> {
    payload
        .get(object_key)
        .and_then(|item| item.get(id_key))
        .map(value_to_string)
        .filter(|value| !value.is_empty())
}

fn value_to_string(value: &Value) -> String {
    match value {
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Bool(value) => value.to_string(),
        _ => String::new(),
    }
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
}

fn short_digest(seed: &str, width: usize) -> String {
    let mut hasher = Sha256::new();
    hasher.update(seed.as_bytes());
    let digest = hex::encode(hasher.finalize());
    digest[..width].to_string()
}
