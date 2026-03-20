use std::process;

fn main() {
    if let Err(error) = musikalisches::run_cli(std::env::args().skip(1)) {
        eprintln!("error: {error:#}");
        process::exit(1);
    }
}
