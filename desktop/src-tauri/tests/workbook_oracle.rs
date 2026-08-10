use std::{collections::BTreeSet, error::Error, fs, io::Read, path::PathBuf};

use g2b_compare_desktop_lib::export_workbook::{
    ComparisonSlot, ExportComparison, ExportLine, TemplateAssets, WorkbookDraft, export_workbook,
};
use serde::Deserialize;
use tempfile::tempdir;
use xmltree::{Element, XMLNode};
use zip::ZipArchive;

fn assets() -> TemplateAssets {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    TemplateAssets::new(
        root.join("src/g2b_compare/assets/estimate-template-v1.xlsx"),
        root.join("src/g2b_compare/assets/estimate-template-v1.json"),
        root.join("src/g2b_compare/assets/estimate-no-image.png"),
    )
}

fn line(index: usize) -> ExportLine {
    let mut line = ExportLine {
        item_name: format!("영상감시장치 {index}"),
        specification: format!("800만화소 {index}"),
        unit: "조".into(),
        quantity: index.to_string(),
        line_kind: "main".into(),
        parent_product_id: None,
        product_id: format!("25{index:06}"),
        company: format!("A 공급사 {index}"),
        unit_price_won: 1_000_000 + i64::try_from(index).unwrap_or_default(),
        comparisons: Vec::new(),
    };
    line.comparisons = [ComparisonSlot::A, ComparisonSlot::B, ComparisonSlot::C]
        .into_iter()
        .map(|slot| {
            let (product_id, company, specification, price_won) = match slot {
                ComparisonSlot::A => (
                    line.product_id.clone(),
                    line.company.clone(),
                    line.specification.clone(),
                    line.unit_price_won,
                ),
                ComparisonSlot::B => (
                    format!("26{index:06}2"),
                    format!("B 공급사 {index}"),
                    format!("비교 규격 B {index}"),
                    900_000,
                ),
                ComparisonSlot::C => (
                    format!("26{index:06}3"),
                    format!("C 공급사 {index}"),
                    format!("비교 규격 C {index}"),
                    1_100_000,
                ),
            };
            ExportComparison {
                slot,
                product_id,
                company,
                specification,
                price_won,
            }
        })
        .collect();
    line
}

fn draft(count: usize) -> WorkbookDraft {
    WorkbookDraft {
        title: "순천 향교 CCTV 구매 설치".into(),
        template_sha256: "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4".into(),
        lines: (1..=count).map(line).collect(),
    }
}

#[derive(Deserialize)]
struct ReferenceCatalog {
    documents: Vec<ReferenceDocument>,
}

#[derive(Deserialize)]
struct ReferenceDocument {
    workbook: String,
    rows: Vec<ReferenceRow>,
}

#[derive(Deserialize)]
struct ReferenceRow {
    quantity: String,
    comparisons: Vec<ReferenceComparison>,
}

#[derive(Clone, Deserialize)]
struct ReferenceComparison {
    slot: ComparisonSlot,
    product_id: String,
    company: String,
    spec: String,
    price_won: i64,
}

fn reference_line(row: &ReferenceRow) -> Result<ExportLine, Box<dyn Error>> {
    let selected = row
        .comparisons
        .first()
        .ok_or("reference row has no slot A")?;
    if selected.slot != ComparisonSlot::A {
        return Err("reference row does not start with slot A".into());
    }
    Ok(ExportLine {
        item_name: "workbook reference".into(),
        specification: selected.spec.clone(),
        unit: "식".into(),
        quantity: row.quantity.clone(),
        line_kind: "main".into(),
        parent_product_id: None,
        product_id: selected.product_id.clone(),
        company: selected.company.clone(),
        unit_price_won: selected.price_won,
        comparisons: row
            .comparisons
            .iter()
            .cloned()
            .map(|comparison| ExportComparison {
                slot: comparison.slot,
                product_id: comparison.product_id,
                company: comparison.company,
                specification: comparison.spec,
                price_won: comparison.price_won,
            })
            .collect(),
    })
}

#[test]
fn one_line_export_is_a_valid_xlsx_with_the_legacy_cell_mapping() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let destination = temporary.path().join("one-line.xlsx");
    let assets = assets();
    let before_template = fs::read(&assets.workbook)?;

    export_workbook(&assets, &destination, &draft(1))?;

    let mut workbook = ZipArchive::new(fs::File::open(&destination)?)?;
    let mut template = ZipArchive::new(fs::File::open(&assets.workbook)?)?;
    assert_eq!(sheet_names(&mut workbook)?, expected_sheet_names());
    assert_eq!(
        cell_text(&mut workbook, "표지 ", "A5")?,
        Some("순천 향교 CCTV 구매 설치".into())
    );
    assert_eq!(
        cell_text(&mut workbook, "수량산출서", "A8")?,
        Some("1-1".into())
    );
    assert_eq!(
        cell_text(&mut workbook, "수량산출서", "B8")?,
        Some("영상감시장치 1".into())
    );
    assert_eq!(
        cell_text(&mut workbook, "수량산출서", "F8")?,
        Some("1".into())
    );
    assert_eq!(
        cell_text(&mut workbook, "단가조사", "F5")?,
        Some("A 공급사 1".into())
    );
    assert_eq!(
        cell_text(&mut workbook, "단가조사", "I5")?,
        Some("1000001".into())
    );
    assert_eq!(
        cell_text(&mut workbook, "단가조사", "J5")?,
        Some("B 공급사 1".into())
    );
    assert_eq!(
        cell_formula(&mut workbook, "단가조사", "E5")?,
        Some("MIN(I5,M5,Q5)".into())
    );
    assert_eq!(
        cell_formula(&mut workbook, "관급내역서", "L19")?,
        Some("SUM(L5:L17)".into())
    );
    assert_eq!(
        cell_formula(&mut workbook, "관급내역서", "L21")?,
        Some("ROUNDUP(SUM(L19:L20),-3)".into())
    );
    assert_eq!(cell_text(&mut workbook, "수량산출서", "B9")?, None);
    assert_eq!(cell_text(&mut workbook, "단가조사", "F6")?, None);
    assert_recalculation_flags(&mut workbook)?;
    assert_preserved_template_parts(&mut template, &mut workbook, &BTreeSet::new())?;
    assert_eq!(fs::read(assets.workbook)?, before_template);
    Ok(())
}

#[test]
fn nine_line_export_preserves_drawings_and_replaces_only_legacy_fallback_image_slots()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let destination = temporary.path().join("nine-lines.xlsx");
    let assets = assets();
    let fallback = fs::read(&assets.fallback_image)?;

    export_workbook(&assets, &destination, &draft(9))?;

    let mut workbook = ZipArchive::new(fs::File::open(&destination)?)?;
    let mut template = ZipArchive::new(fs::File::open(&assets.workbook)?)?;
    assert_eq!(
        cell_text(&mut workbook, "수량산출서", "B16")?,
        Some("영상감시장치 9".into())
    );
    assert_eq!(
        cell_text(&mut workbook, "단가조사", "F13")?,
        Some("A 공급사 9".into())
    );
    assert_eq!(
        read_part(&mut workbook, "xl/drawings/drawing5.xml")?,
        read_part(&mut template, "xl/drawings/drawing5.xml")?
    );
    assert_eq!(
        read_part(&mut workbook, "xl/drawings/_rels/drawing5.xml.rels")?,
        read_part(&mut template, "xl/drawings/_rels/drawing5.xml.rels")?,
    );
    for index in 1..=23 {
        assert_eq!(
            read_part(
                &mut workbook,
                &format!("xl/media/estimate-slot-{index:02}.png")
            )?,
            fallback,
        );
    }
    let changed = (1..=23)
        .map(|index| format!("xl/media/estimate-slot-{index:02}.png"))
        .collect();
    assert_preserved_template_parts(&mut template, &mut workbook, &changed)?;
    Ok(())
}

#[test]
fn legacy_33_row_comparison_corpus_maps_all_a_b_c_values() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let assets = assets();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let catalog: ReferenceCatalog = serde_json::from_slice(&fs::read(
        root.join("src/g2b_compare/web/estimate_comparison_reference.json"),
    )?)?;

    assert_eq!(
        catalog
            .documents
            .iter()
            .map(|document| document.rows.len())
            .collect::<Vec<_>>(),
        [9, 24],
    );
    assert_eq!(
        catalog
            .documents
            .iter()
            .map(|document| document.rows.len())
            .sum::<usize>(),
        33
    );
    assert_eq!(
        catalog
            .documents
            .iter()
            .flat_map(|document| document.rows.iter())
            .map(|row| (&row.comparisons[0].product_id, &row.quantity))
            .collect::<BTreeSet<_>>()
            .len(),
        33,
    );

    for (document_index, document) in catalog.documents.iter().enumerate() {
        for (chunk_index, rows) in document.rows.chunks(9).enumerate() {
            let destination = temporary
                .path()
                .join(format!("{document_index}-{chunk_index}.xlsx"));
            let draft = WorkbookDraft {
                title: document.workbook.clone(),
                template_sha256: "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4"
                    .into(),
                lines: rows.iter().map(reference_line).collect::<Result<_, _>>()?,
            };
            export_workbook(&assets, &destination, &draft)?;
            let mut workbook = ZipArchive::new(fs::File::open(destination)?)?;
            for (index, expected) in rows.iter().enumerate() {
                let row = 5 + index;
                assert_eq!(
                    cell_text(&mut workbook, "수량산출서", &format!("F{}", 8 + index))?,
                    Some(expected.quantity.clone()),
                );
                for comparison in &expected.comparisons {
                    let columns = match comparison.slot {
                        ComparisonSlot::A => ["F", "G", "H", "I"],
                        ComparisonSlot::B => ["J", "K", "L", "M"],
                        ComparisonSlot::C => ["N", "O", "P", "Q"],
                    };
                    assert_eq!(
                        cell_text(&mut workbook, "단가조사", &format!("{}{row}", columns[0]))?,
                        Some(comparison.company.clone()),
                    );
                    assert_eq!(
                        cell_text(&mut workbook, "단가조사", &format!("{}{row}", columns[1]))?,
                        Some(comparison.spec.clone()),
                    );
                    assert_eq!(
                        cell_text(&mut workbook, "단가조사", &format!("{}{row}", columns[2]))?,
                        Some(comparison.product_id.clone()),
                    );
                    assert_eq!(
                        cell_text(&mut workbook, "단가조사", &format!("{}{row}", columns[3]))?,
                        Some(comparison.price_won.to_string()),
                    );
                }
            }
        }
    }
    Ok(())
}

fn expected_sheet_names() -> Vec<String> {
    [
        "수량산출서 (2)",
        "표지 ",
        "설계설명서",
        "설계표지",
        "원가",
        "도급집계표",
        "도급내역서",
        "도급일위대가표",
        "표준품셈",
        "노임단가",
        "관급집계표",
        "관급내역서",
        "수량산출서",
        "단가조사",
        "물가정보",
        "조달물품",
        "설치 구성도",
        "공정표",
        "견적서",
        "견적서2",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}

fn assert_preserved_template_parts(
    template: &mut ZipArchive<fs::File>,
    workbook: &mut ZipArchive<fs::File>,
    changed_media: &BTreeSet<String>,
) -> Result<(), Box<dyn Error>> {
    let mutable = BTreeSet::from([
        "xl/workbook.xml".to_owned(),
        "xl/worksheets/sheet2.xml".to_owned(),
        "xl/worksheets/sheet13.xml".to_owned(),
        "xl/worksheets/sheet14.xml".to_owned(),
    ]);
    let template_names: Vec<_> = template.file_names().map(str::to_owned).collect();
    let workbook_names: Vec<_> = workbook.file_names().map(str::to_owned).collect();
    assert_eq!(template_names.len(), 853);
    assert_eq!(workbook_names, template_names);
    for name in template_names {
        if !mutable.contains(&name) && !changed_media.contains(&name) {
            assert_eq!(
                read_part(template, &name)?,
                read_part(workbook, &name)?,
                "part changed: {name}"
            );
        }
    }
    Ok(())
}

fn sheet_names(archive: &mut ZipArchive<fs::File>) -> Result<Vec<String>, Box<dyn Error>> {
    let workbook = parse_xml(&read_part(archive, "xl/workbook.xml")?)?;
    Ok(workbook
        .get_child("sheets")
        .ok_or("workbook has no sheets")?
        .children
        .iter()
        .filter_map(XMLNode::as_element)
        .filter(|sheet| sheet.name == "sheet")
        .filter_map(|sheet| sheet.attributes.get("name").cloned())
        .collect())
}

fn cell_text(
    archive: &mut ZipArchive<fs::File>,
    sheet_name: &str,
    reference: &str,
) -> Result<Option<String>, Box<dyn Error>> {
    let worksheet = worksheet(archive, sheet_name)?;
    let cell = find_cell(&worksheet, reference);
    Ok(cell.and_then(|cell| {
        if cell
            .attributes
            .get("t")
            .is_some_and(|kind| kind == "inlineStr")
        {
            cell.get_child("is")?
                .get_child("t")?
                .get_text()
                .map(std::borrow::Cow::into_owned)
        } else {
            cell.get_child("v")?
                .get_text()
                .map(std::borrow::Cow::into_owned)
        }
    }))
}

fn cell_formula(
    archive: &mut ZipArchive<fs::File>,
    sheet_name: &str,
    reference: &str,
) -> Result<Option<String>, Box<dyn Error>> {
    let worksheet = worksheet(archive, sheet_name)?;
    Ok(find_cell(&worksheet, reference)
        .and_then(|cell| cell.get_child("f"))
        .and_then(Element::get_text)
        .map(std::borrow::Cow::into_owned))
}

fn assert_recalculation_flags(archive: &mut ZipArchive<fs::File>) -> Result<(), Box<dyn Error>> {
    let workbook = parse_xml(&read_part(archive, "xl/workbook.xml")?)?;
    let calculation = workbook
        .get_child("calcPr")
        .ok_or("workbook has no calcPr")?;
    assert_eq!(calculation.attributes.get("calcMode"), Some(&"auto".into()));
    assert_eq!(
        calculation.attributes.get("fullCalcOnLoad"),
        Some(&"1".into())
    );
    assert_eq!(
        calculation.attributes.get("forceFullCalc"),
        Some(&"1".into())
    );
    Ok(())
}

fn worksheet(
    archive: &mut ZipArchive<fs::File>,
    sheet_name: &str,
) -> Result<Element, Box<dyn Error>> {
    let workbook = parse_xml(&read_part(archive, "xl/workbook.xml")?)?;
    let sheet = workbook
        .get_child("sheets")
        .and_then(|sheets| {
            sheets
                .children
                .iter()
                .filter_map(XMLNode::as_element)
                .find(|sheet| {
                    sheet
                        .attributes
                        .get("name")
                        .is_some_and(|name| name == sheet_name)
                })
        })
        .ok_or("worksheet name absent")?;
    let relation_id = sheet
        .attributes
        .get("id")
        .ok_or("worksheet relationship absent")?;
    let relationships = parse_xml(&read_part(archive, "xl/_rels/workbook.xml.rels")?)?;
    let target = relationships
        .children
        .iter()
        .filter_map(XMLNode::as_element)
        .find(|relationship| relationship.attributes.get("Id") == Some(relation_id))
        .and_then(|relationship| relationship.attributes.get("Target"))
        .ok_or("worksheet target absent")?;
    parse_xml(&read_part(archive, &format!("xl/{target}"))?).map_err(Into::into)
}

fn find_cell<'a>(worksheet: &'a Element, reference: &str) -> Option<&'a Element> {
    worksheet
        .get_child("sheetData")?
        .children
        .iter()
        .filter_map(XMLNode::as_element)
        .filter(|row| row.name == "row")
        .flat_map(|row| row.children.iter().filter_map(XMLNode::as_element))
        .find(|cell| {
            cell.name == "c"
                && cell
                    .attributes
                    .get("r")
                    .is_some_and(|value| value == reference)
        })
}

fn parse_xml(data: &[u8]) -> Result<Element, xmltree::ParseError> {
    Element::parse(data)
}

fn read_part(archive: &mut ZipArchive<fs::File>, name: &str) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut part = archive.by_name(name)?;
    let mut bytes = Vec::new();
    part.read_to_end(&mut bytes)?;
    Ok(bytes)
}
