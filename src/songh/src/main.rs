mod app;
mod cli;
mod config;

use std::process;

fn main() {
    if let Err(error) = app::run(std::env::args().skip(1)) {
        eprintln!("error: {error:#}");
        process::exit(1);
    }
}
