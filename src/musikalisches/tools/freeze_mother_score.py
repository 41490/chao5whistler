#!/usr/bin/env python3

from __future__ import annotations

import json
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

warnings.filterwarnings("ignore")

from music21 import converter, metadata  # type: ignore
import verovio  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = ROOT / "docs/study/music_dice_games_package/mozart_dicegame_print_1790s"
SOURCE_URL = (
    "https://kern.humdrum.org/cgi-bin/ksdata"
    "?file=k516f.krn&l=users/craig/dice/mozart&format=kern"
)
SOURCE_PATH = PACKAGE_DIR / "mother_score.source.k516f.krn"
MUSICXML_PATH = PACKAGE_DIR / "mother_score.musicxml"
MEI_PATH = PACKAGE_DIR / "mother_score.mei"
FRAGMENT_MAP_PATH = PACKAGE_DIR / "fragment_identity_map.json"

XML_NS = {"xml": "http://www.w3.org/XML/1998/namespace"}
MEI_NS_URI = "http://www.music-encoding.org/ns/mei"
ET.register_namespace("", MEI_NS_URI)


def fetch_source() -> None:
    SOURCE_PATH.write_text(
        urllib.request.urlopen(SOURCE_URL).read().decode("utf-8"),
        encoding="utf-8",
    )


def build_musicxml() -> None:
    score = converter.parse(str(SOURCE_PATH))
    score.metadata = metadata.Metadata()
    score.metadata.title = "Musikalisches Wuerfelspiel"
    score.metadata.composer = "traditionally attributed to Wolfgang Amadeus Mozart"
    score.parts[0].partName = "Keyboard Lower Staff"
    score.parts[0].partAbbreviation = "Kb. L."
    score.parts[1].partName = "Keyboard Upper Staff"
    score.parts[1].partAbbreviation = "Kb. U."
    score.write("musicxml", fp=str(MUSICXML_PATH))

    tree = ET.parse(MUSICXML_PATH)
    root = tree.getroot()

    work = root.find("work")
    if work is None:
        work = ET.SubElement(root, "work")
    work_title = work.find("work-title")
    if work_title is None:
        work_title = ET.SubElement(work, "work-title")
    work_title.text = "Musikalisches Wuerfelspiel"

    movement_title = root.find("movement-title")
    if movement_title is None:
        movement_title = ET.SubElement(root, "movement-title")
    movement_title.text = "Musikalisches Wuerfelspiel"

    identification = root.find("identification")
    if identification is None:
        identification = ET.SubElement(root, "identification")

    creator = identification.find("creator")
    if creator is None:
        creator = ET.SubElement(identification, "creator")
    creator.attrib["type"] = "composer"
    creator.text = "traditionally attributed to Wolfgang Amadeus Mozart"

    encoding = identification.find("encoding")
    if encoding is None:
        encoding = ET.SubElement(identification, "encoding")
    software_names = [elem.text for elem in encoding.findall("software")]
    if "freeze_mother_score.py" not in software_names:
        ET.SubElement(encoding, "software").text = "freeze_mother_score.py"

    miscellaneous = identification.find("miscellaneous")
    if miscellaneous is None:
        miscellaneous = ET.SubElement(identification, "miscellaneous")

    misc_fields = {
        "work-id": "mozart_dicegame_print_1790s",
        "canonical-witness-id": "rellstab_1790",
        "verification-witness-id": "simrock_1793",
        "source-humdrum-url": SOURCE_URL,
        "source-humdrum-file": SOURCE_PATH.name,
        "fragment-id-contract": (
            "Measures numbered 1..176 are the canonical fragment ids; "
            "measure number 0 denotes a structural repeat boundary emitted by conversion."
        ),
        "rules-reconciliation-status": (
            "Pending stage 3. The current rules.json and mozart_16x11_table.json "
            "are not yet reconciled against this Rellstab mother score."
        ),
    }
    for key, value in misc_fields.items():
        field = None
        for candidate in miscellaneous.findall("miscellaneous-field"):
            if candidate.attrib.get("name") == key:
                field = candidate
                break
        if field is None:
            field = ET.SubElement(miscellaneous, "miscellaneous-field", {"name": key})
        field.text = value

    tree.write(MUSICXML_PATH, encoding="utf-8", xml_declaration=True)


def build_mei() -> None:
    verovio.enableLog(verovio.LOG_OFF)
    toolkit = verovio.toolkit()
    toolkit.loadFile(str(MUSICXML_PATH))
    MEI_PATH.write_text(toolkit.getMEI(), encoding="utf-8")

    tree = ET.parse(MEI_PATH)
    root = tree.getroot()

    title = root.find(".//{%s}title" % MEI_NS_URI)
    if title is not None:
        title.text = "Musikalisches Wuerfelspiel"

    composer = root.find(".//{%s}persName[@role='composer']" % MEI_NS_URI)
    if composer is not None:
        composer.text = "traditionally attributed to Wolfgang Amadeus Mozart"

    mei_head = root.find("{%s}meiHead" % MEI_NS_URI)
    if mei_head is None:
        raise RuntimeError("MEI output is missing meiHead")

    file_desc = mei_head.find("{%s}fileDesc" % MEI_NS_URI)
    if file_desc is None:
        raise RuntimeError("MEI output is missing fileDesc")

    pub_stmt = file_desc.find("{%s}pubStmt" % MEI_NS_URI)
    if pub_stmt is None:
        pub_stmt = ET.SubElement(file_desc, "{%s}pubStmt" % MEI_NS_URI)

    pub_p = pub_stmt.find("{%s}p" % MEI_NS_URI)
    if pub_p is None:
        pub_p = ET.SubElement(pub_stmt, "{%s}p" % MEI_NS_URI)
    pub_p.text = (
        "Stage 2 mother-score freeze generated from the canonical Humdrum source "
        "for the Rellstab ca.1790 witness."
    )

    encoding_desc = mei_head.find("{%s}encodingDesc" % MEI_NS_URI)
    if encoding_desc is None:
        encoding_desc = ET.SubElement(mei_head, "{%s}encodingDesc" % MEI_NS_URI)

    project_desc = encoding_desc.find("{%s}projectDesc" % MEI_NS_URI)
    if project_desc is None:
        project_desc = ET.SubElement(encoding_desc, "{%s}projectDesc" % MEI_NS_URI)
    project_p = project_desc.find("{%s}p" % MEI_NS_URI)
    if project_p is None:
        project_p = ET.SubElement(project_desc, "{%s}p" % MEI_NS_URI)
    project_p.text = (
        "Measures numbered 1..176 are the canonical fragment ids; "
        "measure number 0 denotes a structural repeat boundary emitted by conversion."
    )

    notes_stmt = file_desc.find("{%s}notesStmt" % MEI_NS_URI)
    if notes_stmt is None:
        notes_stmt = ET.SubElement(file_desc, "{%s}notesStmt" % MEI_NS_URI)
    for text in (
        "work-id: mozart_dicegame_print_1790s",
        "canonical-witness-id: rellstab_1790",
        "verification-witness-id: simrock_1793",
        "source-humdrum-file: mother_score.source.k516f.krn",
    ):
        note = ET.SubElement(notes_stmt, "{%s}annot" % MEI_NS_URI)
        note.text = text

    work_list = mei_head.find("{%s}workList" % MEI_NS_URI)
    if work_list is None:
        work_list = ET.SubElement(mei_head, "{%s}workList" % MEI_NS_URI)
    work = work_list.find("{%s}work" % MEI_NS_URI)
    if work is None:
        work = ET.SubElement(work_list, "{%s}work" % MEI_NS_URI)
    work.attrib["{%s}id" % XML_NS["xml"]] = "mozart_dicegame_print_1790s"
    for text in (
        "canonical-witness-id: rellstab_1790",
        "verification-witness-id: simrock_1793",
    ):
        identifier = ET.SubElement(work, "{%s}identifier" % MEI_NS_URI)
        identifier.text = text

    for measure in root.findall(".//{%s}measure" % MEI_NS_URI):
        measure_number = measure.attrib.get("n", "")
        if measure_number.isdigit() and 1 <= int(measure_number) <= 176:
            measure.attrib["{%s}id" % XML_NS["xml"]] = f"frag{int(measure_number):03d}"

    tree.write(MEI_PATH, encoding="utf-8", xml_declaration=True)


def main() -> None:
    fragment_map = json.loads(FRAGMENT_MAP_PATH.read_text(encoding="utf-8"))
    if fragment_map.get("canonical_witness_id") != "rellstab_1790":
        raise RuntimeError("fragment_identity_map.json must still target rellstab_1790")

    fetch_source()
    build_musicxml()
    build_mei()

    print(f"wrote {SOURCE_PATH.relative_to(ROOT)}")
    print(f"wrote {MUSICXML_PATH.relative_to(ROOT)}")
    print(f"wrote {MEI_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
