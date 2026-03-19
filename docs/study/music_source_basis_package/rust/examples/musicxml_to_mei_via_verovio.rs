use anyhow::{bail, Context, Result};
use std::path::Path;
use std::process::Command;

/// 用法：
///   cargo run --example musicxml_to_mei_via_verovio -- input.musicxml output.mei
///
/// 说明：
/// - Verovio 官方说明支持 MusicXML 与 MEI，并提供命令行工具。
/// - 这个例子让 Rust 只负责流水线编排；真正的 MusicXML->MEI 转换交给 verovio。
/// - 适合把 Mozart / CPE Bach 的 mother_score.musicxml 转成 mother_score.mei 初稿。
fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let input = args.next().context("missing input path")?;
    let output = args.next().context("missing output path")?;

    let input_path = Path::new(&input);
    let output_path = Path::new(&output);

    if !input_path.exists() {
        bail!("input file does not exist: {}", input_path.display());
    }

    // 说明：不同 verovio 版本的参数细节可能略有不同；
    // 这里采用最保守的方式：让 verovio 读 MusicXML，并把结果写到指定输出。
    let status = Command::new("verovio")
        .arg(input_path)
        .arg("-t")
        .arg("musicxml")
        .arg("-o")
        .arg(output_path)
        .status()
        .context("failed to spawn verovio")?;

    if !status.success() {
        bail!("verovio conversion failed with status: {status}");
    }

    println!("Wrote {}", output_path.display());
    Ok(())
}
