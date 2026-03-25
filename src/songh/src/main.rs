mod app;
mod archive;
mod audio;
mod av;
mod cli;
mod config;
mod model;
mod replay;
mod text;
mod video;

use std::process;

fn main() {
    if let Err(error) = app::run(std::env::args().skip(1)) {
        eprintln!("error: {error:#}");
        process::exit(1);
    }
}
