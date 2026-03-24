use std::collections::BTreeMap;

use anyhow::{bail, Result};

use crate::config::schema::TextConfig;

pub fn render_template(config: &TextConfig, fields: &BTreeMap<String, String>) -> Result<String> {
    let mut rendered = String::new();
    let mut rest = config.template.as_str();

    while let Some(start) = rest.find('{') {
        rendered.push_str(&rest[..start]);
        let after_start = &rest[start + 1..];
        let Some(end) = after_start.find('}') else {
            bail!("text.template contains an unclosed placeholder");
        };

        let placeholder = &after_start[..end];
        let mut parts = placeholder.splitn(2, ':');
        let field = parts.next().unwrap_or_default();
        if field.is_empty() {
            bail!("text.template contains an empty placeholder");
        }

        let mut value = fields.get(field).cloned().unwrap_or_default();
        if let Some(width) = parts.next() {
            let width = width.parse::<usize>().map_err(|_| {
                anyhow::anyhow!("text.template has invalid width for field {field}")
            })?;
            value = value.chars().take(width).collect();
        }
        rendered.push_str(&value);
        rest = &after_start[end + 1..];
    }

    if rest.contains('}') {
        bail!("text.template contains a stray closing brace");
    }
    rendered.push_str(rest);

    if !config.allow_multiline {
        rendered = rendered.replace('\n', " ");
    }

    let max_chars = config.max_rendered_chars as usize;
    Ok(rendered.chars().take(max_chars).collect())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::*;
    use crate::config::schema::TextConfig;

    #[test]
    fn render_template_applies_field_width() {
        let config = TextConfig::default();
        let fields = BTreeMap::from([
            ("repo".to_string(), "fixture/repo".to_string()),
            ("hash".to_string(), "deadbeefcafebabe".to_string()),
        ]);

        let rendered = render_template(&config, &fields).expect("render");
        assert_eq!(rendered, "fixture/repo/deadbeef");
    }

    #[test]
    fn render_template_truncates_final_output() {
        let mut config = TextConfig::default();
        config.max_rendered_chars = 12;

        let fields = BTreeMap::from([
            ("repo".to_string(), "fixture/repo".to_string()),
            ("hash".to_string(), "deadbeef".to_string()),
        ]);

        let rendered = render_template(&config, &fields).expect("render");
        assert_eq!(rendered, "fixture/repo");
    }
}
