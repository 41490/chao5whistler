use anyhow::Result;
use quick_xml::events::{BytesStart, Event};
use quick_xml::{Reader, Writer};
use std::fs;
use std::io::Cursor;

/// 目标：
/// - 为每个 MusicXML <measure> 加上稳定的 data-fragment-id
/// - 便于随后转写到 MEI 时映射成 xml:id
///
/// 用法：
///   cargo run --example normalize_musicxml_ids -- in.musicxml out.musicxml prefix
///
/// 例如：
///   cargo run --example normalize_musicxml_ids -- mother_score.musicxml mother_score.norm.musicxml mozart-kac3001
fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let input = args.next().expect("missing input");
    let output = args.next().expect("missing output");
    let prefix = args.next().expect("missing prefix");

    let xml = fs::read_to_string(&input)?;
    let mut reader = Reader::from_str(&xml);
    reader.config_mut().trim_text(false);

    let mut writer = Writer::new(Cursor::new(Vec::new()));
    let mut buf = Vec::new();
    let mut measure_no = 0usize;

    loop {
        match reader.read_event_into(&mut buf)? {
            Event::Start(e) if e.name().as_ref() == b"measure" => {
                measure_no += 1;
                let mut new = BytesStart::new("measure");

                for attr in e.attributes().with_checks(false) {
                    let attr = attr?;
                    new.push_attribute(attr);
                }

                let stable_id = format!("{prefix}-m{:03}", measure_no);
                new.push_attribute(("data-fragment-id", stable_id.as_str()));
                writer.write_event(Event::Start(new))?;
            }
            Event::Empty(e) if e.name().as_ref() == b"measure" => {
                measure_no += 1;
                let mut new = BytesStart::new("measure");

                for attr in e.attributes().with_checks(false) {
                    let attr = attr?;
                    new.push_attribute(attr);
                }

                let stable_id = format!("{prefix}-m{:03}", measure_no);
                new.push_attribute(("data-fragment-id", stable_id.as_str()));
                writer.write_event(Event::Empty(new))?;
            }
            Event::Eof => break,
            ev => writer.write_event(ev)?,
        }
        buf.clear();
    }

    let out = writer.into_inner().into_inner();
    fs::write(output, out)?;
    Ok(())
}
