use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;

use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::Compression;
use serde::de::DeserializeOwned;

use crate::config::schema::NormalizeCodec;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VisitControl {
    Continue,
    Break,
}

pub fn open_gzip_lines(path: &Path) -> Result<impl Iterator<Item = Result<String>>> {
    let file =
        fs::File::open(path).with_context(|| format!("failed to open {}", path.display()))?;
    let reader = BufReader::new(GzDecoder::new(file));
    Ok(reader
        .lines()
        .map(|line| line.context("failed to read gz line")))
}

pub fn write_gzip_json_lines(path: &Path, values: &[serde_json::Value]) -> Result<()> {
    let file =
        fs::File::create(path).with_context(|| format!("failed to create {}", path.display()))?;
    let writer = BufWriter::new(file);
    let mut encoder = GzEncoder::new(writer, Compression::default());
    for value in values {
        let line = serde_json::to_string(value)?;
        encoder
            .write_all(line.as_bytes())
            .with_context(|| format!("failed to write {}", path.display()))?;
        encoder
            .write_all(b"\n")
            .with_context(|| format!("failed to write {}", path.display()))?;
    }
    encoder.finish().context("failed to finalize gz fixture")?;
    Ok(())
}

pub struct EncodedLineWriter {
    inner: EncodedLineWriterKind,
}

enum EncodedLineWriterKind {
    Gzip(GzEncoder<BufWriter<fs::File>>),
    Zstd(zstd::stream::write::Encoder<'static, BufWriter<fs::File>>),
}

impl EncodedLineWriter {
    pub fn write_line(&mut self, line: &str) -> Result<()> {
        match &mut self.inner {
            EncodedLineWriterKind::Gzip(writer) => {
                writer.write_all(line.as_bytes())?;
                writer.write_all(b"\n")?;
            }
            EncodedLineWriterKind::Zstd(writer) => {
                writer.write_all(line.as_bytes())?;
                writer.write_all(b"\n")?;
            }
        }
        Ok(())
    }

    pub fn finish(self) -> Result<()> {
        match self.inner {
            EncodedLineWriterKind::Gzip(writer) => {
                writer.finish().context("failed to finish gzip writer")?;
            }
            EncodedLineWriterKind::Zstd(writer) => {
                writer.finish().context("failed to finish zstd writer")?;
            }
        }
        Ok(())
    }
}

pub fn open_encoded_line_writer(path: &Path, codec: NormalizeCodec) -> Result<EncodedLineWriter> {
    let file =
        fs::File::create(path).with_context(|| format!("failed to create {}", path.display()))?;
    let writer = BufWriter::new(file);
    let inner = match codec {
        NormalizeCodec::JsonlGz => {
            EncodedLineWriterKind::Gzip(GzEncoder::new(writer, Compression::default()))
        }
        NormalizeCodec::JsonlZst => {
            EncodedLineWriterKind::Zstd(zstd::stream::write::Encoder::new(writer, 3)?)
        }
    };
    Ok(EncodedLineWriter { inner })
}

pub fn read_encoded_json_lines<T>(path: &Path) -> Result<Vec<T>>
where
    T: DeserializeOwned,
{
    let mut items = Vec::new();
    visit_encoded_lines(path, |_, line| {
        items.push(serde_json::from_str(line)?);
        Ok(VisitControl::Continue)
    })?;
    Ok(items)
}

pub fn visit_encoded_lines<F>(path: &Path, mut visitor: F) -> Result<()>
where
    F: FnMut(u64, &str) -> Result<VisitControl>,
{
    let file =
        fs::File::open(path).with_context(|| format!("failed to open {}", path.display()))?;
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default();

    let mut reader: Box<dyn BufRead> = match extension {
        "gz" => Box::new(BufReader::new(GzDecoder::new(file))),
        "zst" => Box::new(BufReader::new(zstd::stream::read::Decoder::new(file)?)),
        other => anyhow::bail!("unsupported encoded extension: {other}"),
    };

    let mut line = String::new();
    let mut line_index = 0_u64;
    loop {
        line.clear();
        let read = reader.read_line(&mut line)?;
        if read == 0 {
            break;
        }
        let line = line.trim_end_matches(['\r', '\n']);
        match visitor(line_index, line)? {
            VisitControl::Continue => {
                line_index += 1;
            }
            VisitControl::Break => break,
        }
    }
    Ok(())
}
