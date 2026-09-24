//! Smallest honest `tracing` sink.
//!
//! `tracing` is on the #104 dependency whitelist; `tracing-subscriber` is not,
//! so instead of pulling it in we format events ourselves: `LEVEL k=v ...`
//! one per line on stderr. Spans are unused by rsghsing today.

use std::fmt;
use tracing::field::{Field, Visit};
use tracing::{Event, Level, Metadata, Subscriber};
use tracing::span::{Attributes, Id, Record};

pub fn init(level: Level) {
    let _ = tracing::subscriber::set_global_default(Stderr(level));
}

pub struct Stderr(pub Level);

#[derive(Default)]
struct Fields(String);

impl Visit for Fields {
    fn record_debug(&mut self, field: &Field, value: &dyn fmt::Debug) {
        if !self.0.is_empty() {
            self.0.push(' ');
        }
        if field.name() == "message" {
            self.0.push_str(&format!("{value:?}"));
        } else {
            self.0.push_str(&format!("{}={:?}", field.name(), value));
        }
    }
}

impl Subscriber for Stderr {
    fn enabled(&self, meta: &Metadata<'_>) -> bool {
        *meta.level() <= self.0
    }

    fn new_span(&self, _: &Attributes<'_>) -> Id {
        Id::from_u64(1)
    }

    fn record(&self, _: &Id, _: &Record<'_>) {}
    fn record_follows_from(&self, _: &Id, _: &Id) {}
    fn enter(&self, _: &Id) {}
    fn exit(&self, _: &Id) {}

    fn event(&self, event: &Event<'_>) {
        let mut fields = Fields::default();
        event.record(&mut fields);
        eprintln!("{} {}", event.metadata().level(), fields.0);
    }
}
