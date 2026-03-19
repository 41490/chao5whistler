use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MozartDiceGameRules {
    pub work_id: String,
    pub rolls: [u8; 11],
    pub columns: BTreeMap<String, [u16; 11]>,
}

impl MozartDiceGameRules {
    pub fn fragment_for(&self, column: &str, roll_sum: u8) -> Option<u16> {
        let idx = self.rolls.iter().position(|r| *r == roll_sum)?;
        self.columns.get(column).map(|col| col[idx])
    }

    pub fn realize(&self, roll_sums: [u8; 16]) -> anyhow::Result<Vec<u16>> {
        let order = [
            "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
            "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8",
        ];

        let mut out = Vec::with_capacity(16);
        for (col, roll) in order.iter().zip(roll_sums) {
            let frag = self
                .fragment_for(col, roll)
                .ok_or_else(|| anyhow::anyhow!("invalid column/roll: {col} / {roll}"))?;
            out.push(frag);
        }
        Ok(out)
    }
}

fn main() -> anyhow::Result<()> {
    let json = include_str!("../../docs/mozart_16x11_table.json");
    let rules: MozartDiceGameRules = serde_json::from_str(json)?;

    let roll_sums = [2, 5, 10, 6, 3, 8, 9, 9, 7, 4, 11, 6, 8, 12, 7, 10];
    let piece = rules.realize(roll_sums)?;

    println!("Selected fragment ids: {piece:?}");
    Ok(())
}
