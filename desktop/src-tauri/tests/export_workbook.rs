use std::{error::Error, fs, io::Read, path::PathBuf};

use g2b_compare_desktop_lib::export_workbook::{
    ComparisonSlot, ExportComparison, ExportLine, ExportWorkbookError, TemplateAssets,
    WorkbookDraft, export_workbook,
};
use tempfile::tempdir;

fn assets() -> TemplateAssets {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    TemplateAssets::new(
        root.join("src/g2b_compare/assets/estimate-template-v1.xlsx"),
        root.join("src/g2b_compare/assets/estimate-template-v1.json"),
        root.join("src/g2b_compare/assets/estimate-no-image.png"),
    )
}

fn comparison(slot: ComparisonSlot, index: usize, line: &ExportLine) -> ExportComparison {
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
            format!("비교 규격 C {index}"),
            format!("C 공급사 {index}"),
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
        .map(|slot| comparison(slot, index, &line))
        .collect();
    line
}

fn draft(line_count: usize) -> WorkbookDraft {
    WorkbookDraft {
        title: "순천 향교 CCTV 구매 설치".into(),
        template_sha256: "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4".into(),
        lines: (1..=line_count).map(line).collect(),
    }
}

#[test]
fn export_is_deterministic_for_the_same_template_and_snapshot() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let first = temporary.path().join("first.xlsx");
    let second = temporary.path().join("second.xlsx");

    export_workbook(&assets(), &first, &draft(1))?;
    export_workbook(&assets(), &second, &draft(1))?;

    assert_eq!(fs::read(first)?, fs::read(second)?);
    Ok(())
}

#[test]
fn publication_is_atomic_and_never_overwrites_the_source_template() -> Result<(), Box<dyn Error>> {
    let assets = assets();
    let original = fs::read(&assets.workbook)?;

    let result = export_workbook(&assets, &assets.workbook, &draft(1));

    assert!(matches!(result, Err(ExportWorkbookError::SourceOverwrite)));
    assert_eq!(fs::read(assets.workbook)?, original);
    Ok(())
}

#[test]
fn existing_destination_fails_closed_without_partial_workbook() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let destination = temporary.path().join("export.xlsx");
    fs::write(&destination, b"keep existing export")?;

    let result = export_workbook(&assets(), &destination, &draft(1));

    assert!(matches!(
        result,
        Err(ExportWorkbookError::DestinationExists { .. })
    ));
    assert_eq!(fs::read(&destination)?, b"keep existing export");
    assert!(!destination.with_extension("xlsx.tmp").exists());
    Ok(())
}

#[test]
fn export_rejects_a_draft_pinned_to_a_different_template() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let destination = temporary.path().join("blocked.xlsx");
    let mut mismatch = draft(1);
    mismatch.template_sha256 = "a".repeat(64);

    let result = export_workbook(&assets(), &destination, &mismatch);

    assert!(matches!(
        result,
        Err(ExportWorkbookError::TemplateHashChanged)
    ));
    assert!(!destination.exists());
    Ok(())
}

#[test]
fn export_rejects_incomplete_comparisons_and_mismatched_slot_a() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let destination = temporary.path().join("blocked.xlsx");
    let mut incomplete = draft(1);
    let _ = incomplete.lines[0].comparisons.pop();

    assert!(matches!(
        export_workbook(&assets(), &destination, &incomplete),
        Err(ExportWorkbookError::ComparisonsRequired)
    ));
    assert!(!destination.exists());

    let mut mismatch = draft(1);
    mismatch.lines[0].comparisons[0].company = "다른 공급사".into();
    assert!(matches!(
        export_workbook(&assets(), &destination, &mismatch),
        Err(ExportWorkbookError::ComparisonsRequired)
    ));
    assert!(!destination.exists());
    Ok(())
}

#[test]
fn formula_looking_imported_text_is_written_as_a_literal_string() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let destination = temporary.path().join("literal.xlsx");
    let mut exported = draft(1);
    exported.lines[0].item_name = "=SUM(F8:F9)".into();

    export_workbook(&assets(), &destination, &exported)?;

    let mut archive = zip::ZipArchive::new(fs::File::open(destination)?)?;
    let mut quantity = String::new();
    archive
        .by_name("xl/worksheets/sheet13.xml")?
        .read_to_string(&mut quantity)?;
    assert!(quantity.contains(r#"r="B8""#));
    assert!(quantity.contains(r#"t="inlineStr""#));
    assert!(quantity.contains("=SUM(F8:F9)"));
    Ok(())
}
