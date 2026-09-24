//! `audio`: v2 ambient DSP, ported from `src/ghsingo/internal/audio`.
//!
//! Scope = the render-audio-v2 / live-v2 call chain only. The backend
//! abstraction (`backend/backend.go`), its scsynth and gov2 implementations,
//! and `lifecycle` are deliberately NOT ported — see the P2 report's ablation
//! list for the call-chain evidence.

pub mod bed;
pub mod bellbank;
pub mod drone;
pub mod karplus;
pub mod mixer;
pub mod pitch;
pub mod reverb;
pub mod tonal_bed;
pub mod wav;
