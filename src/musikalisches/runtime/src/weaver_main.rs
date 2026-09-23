//! Entry point for the `musikalisches-weaver` supervisor binary.

use std::process;

fn main() {
    let exit_code = musikalisches::weaver::run_cli(std::env::args().skip(1).collect());
    process::exit(exit_code);
}
