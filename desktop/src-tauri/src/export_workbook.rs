//! Immutable-template estimate workbook export.
//!
//! Only `표지 !A5`, `수량산출서` rows 8-16, `단가조사` rows 5-13, and
//! workbook recalculation flags are changed. Every other OOXML ZIP part is
//! copied without parsing so legacy drawings, relationships, formulas, media,
//! `ActiveX` controls, and future unknown parts survive an export.

use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::{self, BufRead, Cursor, ErrorKind, Read, Write},
    path::{Path, PathBuf},
};

use quick_xml::{
    Reader, Writer,
    events::{BytesEnd, BytesStart, BytesText, Event},
};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use thiserror::Error;
use zip::{
    CompressionMethod, DateTime, ZipArchive, ZipWriter, result::ZipError, write::SimpleFileOptions,
};

const EXPECTED_TEMPLATE_SHA256: &str =
    "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4";
const EXPECTED_SHEET_NAMES: [&str; 20] = [
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
];
const TITLE_SHEET: &str = "표지 ";
const QUANTITY_SHEET: &str = "수량산출서";
const PRICE_SHEET: &str = "단가조사";
const TITLE_CELL: &str = "A5";
const QUANTITY_START_ROW: u32 = 8;
const PRICE_START_ROW: u32 = 5;
const MAX_LINES: usize = 9;
const IMAGE_SLOT_COUNT: usize = 23;
const EXPECTED_IMAGE_SLOT_LINE_INDICES: [usize; IMAGE_SLOT_COUNT] = [
    7, 7, 7, 6, 6, 6, 5, 8, 8, 8, 4, 3, 2, 1, 1, 3, 4, 2, 5, 1, 2, 3, 5,
];

/// The immutable, bundled files needed to create an estimate workbook.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemplateAssets {
    /// The fixed OOXML workbook template.
    pub workbook: PathBuf,
    /// The checksum-locked manifest for the fixed template.
    pub manifest: PathBuf,
    /// The legacy image used for populated comparison image placeholders.
    pub fallback_image: PathBuf,
}

impl TemplateAssets {
    /// Binds the three immutable packaged assets used by an export.
    #[must_use]
    pub const fn new(workbook: PathBuf, manifest: PathBuf, fallback_image: PathBuf) -> Self {
        Self {
            workbook,
            manifest,
            fallback_image,
        }
    }
}

/// One A, B, or C comparison slot in the fixed `단가조사` sheet.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd)]
#[serde(rename_all = "UPPERCASE")]
pub enum ComparisonSlot {
    /// The selected product, which must exactly match its estimate line.
    A,
    /// The first comparison product.
    B,
    /// The second comparison product.
    C,
}

/// One immutable comparison value set for a line.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExportComparison {
    /// The A, B, or C output slot.
    pub slot: ComparisonSlot,
    /// The procurement product identifier.
    pub product_id: String,
    /// The supplier snapshot.
    pub company: String,
    /// The specification snapshot.
    pub specification: String,
    /// The unit price in won.
    pub price_won: i64,
}

/// One persisted estimate line in workbook-export form.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExportLine {
    /// The line item name.
    pub item_name: String,
    /// The selected-product specification.
    pub specification: String,
    /// The output unit.
    pub unit: String,
    /// A database-normalized decimal quantity.
    pub quantity: String,
    /// `main` for a base item, otherwise an option line.
    pub line_kind: String,
    /// The parent product used in legacy option labels.
    pub parent_product_id: Option<String>,
    /// The selected product identifier.
    pub product_id: String,
    /// The selected supplier snapshot.
    pub company: String,
    /// The selected unit price snapshot in won.
    pub unit_price_won: i64,
    /// The complete A/B/C comparison snapshots.
    pub comparisons: Vec<ExportComparison>,
}

/// All persisted values consumed by the workbook mapper.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkbookDraft {
    /// The document title written to `표지 !A5`.
    pub title: String,
    /// The template checksum pinned with the persisted draft.
    pub template_sha256: String,
    /// At most nine persisted lines, ordered by their estimate line number.
    pub lines: Vec<ExportLine>,
}

/// Errors returned before any partially written workbook can be published.
#[derive(Debug, Error)]
pub enum ExportWorkbookError {
    #[error("source workbook {path} cannot be read: {source}")]
    SourceRead {
        /// Source path.
        path: PathBuf,
        /// Filesystem failure.
        #[source]
        source: io::Error,
    },
    #[error("source workbook {path} is not a regular file")]
    InvalidSource {
        /// Source path.
        path: PathBuf,
    },
    #[error("template manifest {path} cannot be read: {source}")]
    ManifestRead {
        /// Manifest path.
        path: PathBuf,
        /// Filesystem failure.
        #[source]
        source: io::Error,
    },
    #[error("template manifest {path} is invalid: {source}")]
    ManifestParse {
        /// Manifest path.
        path: PathBuf,
        /// JSON decoding failure.
        #[source]
        source: serde_json::Error,
    },
    #[error("template manifest is not the fixed estimate workbook manifest")]
    ManifestChanged,
    #[error("기준 템플릿 해시가 일치하지 않음")]
    TemplateHashChanged,
    #[error("기준 템플릿 시트 순서가 바뀜")]
    TemplateSheetsChanged,
    #[error("template workbook {path} is not a valid OOXML archive: {source}")]
    InvalidArchive {
        /// Template path.
        path: PathBuf,
        /// ZIP decoding failure.
        #[source]
        source: ZipError,
    },
    #[error("template workbook XML part {part} is invalid: {source}")]
    XmlParse {
        /// ZIP part name.
        part: String,
        /// XML decoding failure.
        #[source]
        source: quick_xml::Error,
    },
    #[error("template workbook XML part {part} has an invalid attribute: {detail}")]
    XmlAttribute {
        /// ZIP part name.
        part: String,
        /// Invalid attribute detail.
        detail: String,
    },
    #[error("template workbook is missing required OOXML part {part}")]
    MissingPart {
        /// Required ZIP part name.
        part: String,
    },
    #[error("template workbook has no worksheet data in {sheet}")]
    MissingSheetData {
        /// Worksheet name.
        sheet: String,
    },
    #[error("template workbook has no mapped cell {cell} in {sheet}")]
    MissingCell {
        /// Worksheet name.
        sheet: String,
        /// Cell reference.
        cell: String,
    },
    #[error("an estimate can contain at most nine lines")]
    LineLimit,
    #[error("비교 물품 2개가 필요함")]
    ComparisonsRequired,
    #[error("the source workbook must not be used as an export destination")]
    SourceOverwrite,
    #[error("destination {path} is invalid")]
    InvalidDestination {
        /// Destination path.
        path: PathBuf,
    },
    #[error("destination {path} already exists")]
    DestinationExists {
        /// Destination path.
        path: PathBuf,
    },
    #[error("temporary export {path} already exists")]
    TemporaryExists {
        /// Temporary path.
        path: PathBuf,
    },
    #[error("temporary export {path} cannot be created: {source}")]
    TemporaryCreate {
        /// Temporary path.
        path: PathBuf,
        /// Filesystem failure.
        #[source]
        source: io::Error,
    },
    #[error("temporary export {path} cannot be written: {source}")]
    TemporaryWrite {
        /// Temporary path.
        path: PathBuf,
        /// Filesystem failure.
        #[source]
        source: io::Error,
    },
    #[error("temporary export {path} cannot be synchronized: {source}")]
    TemporarySync {
        /// Temporary path.
        path: PathBuf,
        /// Filesystem failure.
        #[source]
        source: io::Error,
    },
    #[error("temporary export {temporary} cannot be published to {destination}: {source}")]
    Publish {
        /// Temporary path.
        temporary: PathBuf,
        /// Final destination.
        destination: PathBuf,
        /// Filesystem failure.
        #[source]
        source: io::Error,
    },
    #[error("temporary export {path} could not be cleaned up: {source}")]
    TemporaryCleanup {
        /// Temporary path.
        path: PathBuf,
        /// Filesystem failure.
        #[source]
        source: io::Error,
    },
}

/// Mutates a validated copy of the fixed template and atomically publishes it.
///
/// The input draft must retain its original template checksum and complete A/B/C
/// snapshots for every line. Imported text is always emitted as an OOXML
/// `inlineStr`, so a leading `=` stays literal spreadsheet text.
///
/// # Errors
///
/// Returns [`ExportWorkbookError`] before publication if the immutable assets,
/// persisted draft, output path, or OOXML template contract is invalid.
pub fn export_workbook(
    assets: &TemplateAssets,
    destination: &Path,
    draft: &WorkbookDraft,
) -> Result<(), ExportWorkbookError> {
    let manifest = load_manifest(&assets.manifest)?;
    validate_manifest(&manifest)?;
    validate_source(&assets.workbook)?;
    validate_draft(draft, &manifest)?;

    let temporary = temporary_path(destination);
    preflight_destination(&assets.workbook, destination, &temporary)?;
    let mutations = build_mutations(&assets.workbook, &assets.fallback_image, draft, &manifest)?;
    write_temporary(&temporary, |file| {
        write_archive(&assets.workbook, file, &mutations)
    })?;
    publish_temporary(&temporary, destination)
}

#[derive(Debug, Deserialize)]
struct TemplateManifest {
    template_sha256: String,
    sheet_names: Vec<String>,
    title_cell: CellCoordinate,
    quantity_rows: RowRange,
    price_rows: RowRange,
    image_slots: Vec<ImageSlot>,
}

#[derive(Debug, Deserialize)]
struct CellCoordinate {
    sheet: String,
    cell: String,
}

#[derive(Debug, Deserialize)]
struct RowRange {
    sheet: String,
    start_row: u32,
    count: usize,
}

#[derive(Debug, Deserialize)]
struct ImageSlot {
    line_index: usize,
    media_path: String,
}

#[derive(Clone, Debug)]
enum CellValue {
    Clear,
    Text(String),
    Number(String),
}

fn load_manifest(path: &Path) -> Result<TemplateManifest, ExportWorkbookError> {
    let data = fs::read(path).map_err(|source| ExportWorkbookError::ManifestRead {
        path: path.to_path_buf(),
        source,
    })?;
    serde_json::from_slice(&data).map_err(|source| ExportWorkbookError::ManifestParse {
        path: path.to_path_buf(),
        source,
    })
}

fn validate_manifest(manifest: &TemplateManifest) -> Result<(), ExportWorkbookError> {
    let expected_sheets = EXPECTED_SHEET_NAMES.map(str::to_owned);
    let manifest_media_paths = manifest
        .image_slots
        .iter()
        .map(|slot| slot.media_path.clone())
        .collect::<BTreeSet<_>>();
    if manifest.template_sha256 != EXPECTED_TEMPLATE_SHA256
        || manifest.sheet_names != expected_sheets
        || manifest.title_cell.sheet != TITLE_SHEET
        || manifest.title_cell.cell != TITLE_CELL
        || manifest.quantity_rows.sheet != QUANTITY_SHEET
        || manifest.quantity_rows.start_row != QUANTITY_START_ROW
        || manifest.quantity_rows.count != MAX_LINES
        || manifest.price_rows.sheet != PRICE_SHEET
        || manifest.price_rows.start_row != PRICE_START_ROW
        || manifest.price_rows.count != MAX_LINES
        || manifest.image_slots.len() != IMAGE_SLOT_COUNT
        || manifest_media_paths != expected_image_slot_paths()
        || manifest
            .image_slots
            .iter()
            .zip(EXPECTED_IMAGE_SLOT_LINE_INDICES)
            .enumerate()
            .any(|(index, (slot, line_index))| {
                slot.line_index != line_index
                    || slot.media_path != format!("xl/media/estimate-slot-{:02}.png", index + 1)
            })
    {
        return Err(ExportWorkbookError::ManifestChanged);
    }
    Ok(())
}

fn expected_image_slot_paths() -> BTreeSet<String> {
    (1..=IMAGE_SLOT_COUNT)
        .map(|index| format!("xl/media/estimate-slot-{index:02}.png"))
        .collect()
}

fn validate_source(source: &Path) -> Result<(), ExportWorkbookError> {
    let metadata =
        fs::metadata(source).map_err(|source_error| ExportWorkbookError::SourceRead {
            path: source.to_path_buf(),
            source: source_error,
        })?;
    if !metadata.is_file() {
        return Err(ExportWorkbookError::InvalidSource {
            path: source.to_path_buf(),
        });
    }
    Ok(())
}

fn validate_draft(
    draft: &WorkbookDraft,
    manifest: &TemplateManifest,
) -> Result<(), ExportWorkbookError> {
    if draft.template_sha256 != manifest.template_sha256 {
        return Err(ExportWorkbookError::TemplateHashChanged);
    }
    if draft.lines.len() > MAX_LINES {
        return Err(ExportWorkbookError::LineLimit);
    }
    for line in &draft.lines {
        validate_line_comparisons(line)?;
    }
    Ok(())
}

fn validate_line_comparisons(line: &ExportLine) -> Result<(), ExportWorkbookError> {
    let mut by_slot = BTreeMap::new();
    for comparison in &line.comparisons {
        if by_slot.insert(comparison.slot, comparison).is_some() {
            return Err(ExportWorkbookError::ComparisonsRequired);
        }
    }
    let Some(selected) = by_slot.get(&ComparisonSlot::A) else {
        return Err(ExportWorkbookError::ComparisonsRequired);
    };
    let selected_price_matches = selected.price_won == line.unit_price_won;
    if by_slot.len() != 3
        || !by_slot.contains_key(&ComparisonSlot::B)
        || !by_slot.contains_key(&ComparisonSlot::C)
        || selected.product_id != line.product_id
        || selected.company != line.company
        || selected.specification != line.specification
        || !selected_price_matches
    {
        return Err(ExportWorkbookError::ComparisonsRequired);
    }
    Ok(())
}

fn preflight_destination(
    source: &Path,
    destination: &Path,
    temporary: &Path,
) -> Result<(), ExportWorkbookError> {
    let parent = destination_parent(destination)?;
    fs::create_dir_all(parent).map_err(|_| ExportWorkbookError::InvalidDestination {
        path: destination.to_path_buf(),
    })?;
    let parent_metadata =
        fs::metadata(parent).map_err(|_| ExportWorkbookError::InvalidDestination {
            path: destination.to_path_buf(),
        })?;
    if !parent_metadata.is_dir() || destination.file_name().is_none() {
        return Err(ExportWorkbookError::InvalidDestination {
            path: destination.to_path_buf(),
        });
    }

    let source_path =
        fs::canonicalize(source).map_err(|source_error| ExportWorkbookError::SourceRead {
            path: source.to_path_buf(),
            source: source_error,
        })?;
    let parent_path =
        fs::canonicalize(parent).map_err(|_| ExportWorkbookError::InvalidDestination {
            path: destination.to_path_buf(),
        })?;
    let destination_path = parent_path.join(destination.file_name().ok_or_else(|| {
        ExportWorkbookError::InvalidDestination {
            path: destination.to_path_buf(),
        }
    })?);
    if source_path == destination_path {
        return Err(ExportWorkbookError::SourceOverwrite);
    }
    reject_existing_destination(destination, &source_path, false)?;
    reject_existing_destination(temporary, &source_path, true)
}

fn destination_parent(destination: &Path) -> Result<&Path, ExportWorkbookError> {
    match destination.parent() {
        Some(parent) if parent.as_os_str().is_empty() => Ok(Path::new(".")),
        Some(parent) => Ok(parent),
        None => Err(ExportWorkbookError::InvalidDestination {
            path: destination.to_path_buf(),
        }),
    }
}

fn reject_existing_destination(
    path: &Path,
    source_path: &Path,
    temporary: bool,
) -> Result<(), ExportWorkbookError> {
    match fs::symlink_metadata(path) {
        Ok(_) if path_resolves_to_source(path, source_path) => {
            Err(ExportWorkbookError::SourceOverwrite)
        }
        Ok(_) if temporary => Err(ExportWorkbookError::TemporaryExists {
            path: path.to_path_buf(),
        }),
        Ok(_) => Err(ExportWorkbookError::DestinationExists {
            path: path.to_path_buf(),
        }),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(_) => Err(ExportWorkbookError::InvalidDestination {
            path: path.to_path_buf(),
        }),
    }
}

fn path_resolves_to_source(path: &Path, source_path: &Path) -> bool {
    fs::canonicalize(path).is_ok_and(|existing| existing == source_path)
}

fn temporary_path(destination: &Path) -> PathBuf {
    let mut temporary = destination.as_os_str().to_os_string();
    temporary.push(".tmp");
    PathBuf::from(temporary)
}

fn build_mutations(
    source: &Path,
    fallback_image: &Path,
    draft: &WorkbookDraft,
    manifest: &TemplateManifest,
) -> Result<BTreeMap<String, Vec<u8>>, ExportWorkbookError> {
    if sha256_file(source)? != manifest.template_sha256 {
        return Err(ExportWorkbookError::TemplateHashChanged);
    }
    let source_file =
        File::open(source).map_err(|source_error| ExportWorkbookError::SourceRead {
            path: source.to_path_buf(),
            source: source_error,
        })?;
    let mut archive = ZipArchive::new(source_file).map_err(|source_error| {
        ExportWorkbookError::InvalidArchive {
            path: source.to_path_buf(),
            source: source_error,
        }
    })?;
    let workbook = read_part(&mut archive, "xl/workbook.xml")?;
    let relationships = read_part(&mut archive, "xl/_rels/workbook.xml.rels")?;
    let paths = sheet_paths(&workbook, &relationships)?;
    let title_path = required_sheet_path(&paths, TITLE_SHEET)?;
    let quantity_path = required_sheet_path(&paths, QUANTITY_SHEET)?;
    let price_path = required_sheet_path(&paths, PRICE_SHEET)?;

    let title = mutate_worksheet(
        &read_part(&mut archive, title_path)?,
        TITLE_SHEET,
        &BTreeMap::from([(TITLE_CELL.to_owned(), CellValue::Text(draft.title.clone()))]),
    )?;
    let quantities = mutate_worksheet(
        &read_part(&mut archive, quantity_path)?,
        QUANTITY_SHEET,
        &quantity_cells(draft),
    )?;
    let prices = mutate_worksheet(
        &read_part(&mut archive, price_path)?,
        PRICE_SHEET,
        &price_cells(draft),
    )?;
    let workbook = mutate_workbook(&workbook)?;

    let mut mutations = BTreeMap::from([
        (title_path.to_owned(), title),
        (quantity_path.to_owned(), quantities),
        (price_path.to_owned(), prices),
        ("xl/workbook.xml".to_owned(), workbook),
    ]);
    replace_legacy_image_slots(
        &mut archive,
        fallback_image,
        draft.lines.len(),
        manifest,
        &mut mutations,
    )?;
    Ok(mutations)
}

fn sha256_file(path: &Path) -> Result<String, ExportWorkbookError> {
    let mut file = File::open(path).map_err(|source| ExportWorkbookError::SourceRead {
        path: path.to_path_buf(),
        source,
    })?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0_u8; 64 * 1024].into_boxed_slice();
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|source| ExportWorkbookError::SourceRead {
                path: path.to_path_buf(),
                source,
            })?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn sheet_paths(
    workbook: &[u8],
    relationships: &[u8],
) -> Result<BTreeMap<String, String>, ExportWorkbookError> {
    let sheets = sheet_records(workbook, "xl/workbook.xml")?;
    if sheets
        .iter()
        .map(|sheet| sheet.name.as_str())
        .collect::<Vec<_>>()
        != EXPECTED_SHEET_NAMES
    {
        return Err(ExportWorkbookError::TemplateSheetsChanged);
    }
    let targets = relationship_targets(relationships, "xl/_rels/workbook.xml.rels")?;
    sheets
        .into_iter()
        .map(|sheet| {
            let target = targets
                .get(&sheet.relationship_id)
                .ok_or(ExportWorkbookError::TemplateSheetsChanged)?;
            let path = worksheet_path(target).ok_or(ExportWorkbookError::TemplateSheetsChanged)?;
            Ok((sheet.name, path))
        })
        .collect()
}

#[derive(Debug)]
struct SheetRecord {
    name: String,
    relationship_id: String,
}

fn sheet_records(data: &[u8], part: &str) -> Result<Vec<SheetRecord>, ExportWorkbookError> {
    let mut reader = xml_reader(data);
    let mut buffer = Vec::new();
    let mut sheets = Vec::new();
    loop {
        match read_event(&mut reader, &mut buffer, part)? {
            Event::Start(event) | Event::Empty(event)
                if local_name(event.name().as_ref()) == b"sheet" =>
            {
                let name = required_attribute(&event, b"name", part)?;
                let relationship_id = required_attribute(&event, b"id", part)?;
                sheets.push(SheetRecord {
                    name,
                    relationship_id,
                });
            }
            Event::Eof => break,
            _ => {}
        }
        buffer.clear();
    }
    Ok(sheets)
}

fn relationship_targets(
    data: &[u8],
    part: &str,
) -> Result<BTreeMap<String, String>, ExportWorkbookError> {
    let mut reader = xml_reader(data);
    let mut buffer = Vec::new();
    let mut targets = BTreeMap::new();
    loop {
        match read_event(&mut reader, &mut buffer, part)? {
            Event::Start(event) | Event::Empty(event)
                if local_name(event.name().as_ref()) == b"Relationship" =>
            {
                let id = required_attribute(&event, b"Id", part)?;
                let target = required_attribute(&event, b"Target", part)?;
                let _ = targets.insert(id, target);
            }
            Event::Eof => break,
            _ => {}
        }
        buffer.clear();
    }
    Ok(targets)
}

fn worksheet_path(target: &str) -> Option<String> {
    let target = target.strip_prefix('/').unwrap_or(target);
    let target = target.strip_prefix("xl/").unwrap_or(target);
    if target.starts_with("worksheets/")
        && Path::new(target)
            .extension()
            .is_some_and(|extension| extension.eq_ignore_ascii_case("xml"))
        && !target.split('/').any(|part| part == "..")
    {
        Some(format!("xl/{target}"))
    } else {
        None
    }
}

fn required_sheet_path<'a>(
    paths: &'a BTreeMap<String, String>,
    sheet: &str,
) -> Result<&'a str, ExportWorkbookError> {
    paths
        .get(sheet)
        .map(String::as_str)
        .ok_or(ExportWorkbookError::TemplateSheetsChanged)
}

fn quantity_cells(draft: &WorkbookDraft) -> BTreeMap<String, CellValue> {
    let mut cells = BTreeMap::new();
    for index in 0..MAX_LINES {
        let row = QUANTITY_START_ROW + u32::try_from(index).unwrap_or_default();
        for column in ["A", "B", "C", "D", "F", "G", "H", "I", "K"] {
            let _ = cells.insert(format!("{column}{row}"), CellValue::Clear);
        }
        let Some(line) = draft.lines.get(index) else {
            continue;
        };
        let kind = if line.line_kind == "main" {
            "본품".to_owned()
        } else {
            format!(
                "{} 옵션",
                line.parent_product_id.as_deref().unwrap_or_default()
            )
        };
        for (column, value) in [
            ("A", CellValue::Text(format!("1-{}", index + 1))),
            ("B", CellValue::Text(line.item_name.clone())),
            ("C", CellValue::Text(line.specification.clone())),
            ("D", CellValue::Text(line.unit.clone())),
            ("F", CellValue::Number(line.quantity.clone())),
            ("K", CellValue::Text(kind)),
        ] {
            let _ = cells.insert(format!("{column}{row}"), value);
        }
    }
    cells
}

fn price_cells(draft: &WorkbookDraft) -> BTreeMap<String, CellValue> {
    let mut cells = BTreeMap::new();
    for index in 0..MAX_LINES {
        let row = PRICE_START_ROW + u32::try_from(index).unwrap_or_default();
        for column in ["F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q"] {
            let _ = cells.insert(format!("{column}{row}"), CellValue::Clear);
        }
        let Some(line) = draft.lines.get(index) else {
            continue;
        };
        for comparison in &line.comparisons {
            let columns = match comparison.slot {
                ComparisonSlot::A => ["F", "G", "H", "I"],
                ComparisonSlot::B => ["J", "K", "L", "M"],
                ComparisonSlot::C => ["N", "O", "P", "Q"],
            };
            for (column, value) in [
                (columns[0], CellValue::Text(comparison.company.clone())),
                (
                    columns[1],
                    CellValue::Text(comparison.specification.clone()),
                ),
                (columns[2], CellValue::Text(comparison.product_id.clone())),
                (
                    columns[3],
                    CellValue::Number(comparison.price_won.to_string()),
                ),
            ] {
                let _ = cells.insert(format!("{column}{row}"), value);
            }
        }
    }
    cells
}

fn mutate_worksheet(
    data: &[u8],
    sheet: &str,
    cells: &BTreeMap<String, CellValue>,
) -> Result<Vec<u8>, ExportWorkbookError> {
    let mut reader = xml_reader(data);
    let mut writer = Writer::new(Vec::with_capacity(data.len()));
    let mut buffer = Vec::new();
    let mut found = BTreeSet::new();
    let mut sheet_data = false;
    loop {
        let event = read_event(&mut reader, &mut buffer, sheet)?;
        match event {
            Event::Start(event) if local_name(event.name().as_ref()) == b"sheetData" => {
                sheet_data = true;
                write_event(&mut writer, Event::Start(event))?;
            }
            Event::Start(event) if local_name(event.name().as_ref()) == b"c" => {
                let reference = optional_attribute(&event, b"r", sheet)?;
                if let Some(reference) = reference.filter(|reference| cells.contains_key(reference))
                {
                    let value =
                        cells
                            .get(&reference)
                            .ok_or_else(|| ExportWorkbookError::MissingCell {
                                sheet: sheet.to_owned(),
                                cell: reference.clone(),
                            })?;
                    write_cell(&mut writer, &event, value)?;
                    let _ = found.insert(reference);
                    buffer.clear();
                    skip_element(&mut reader, &mut buffer, sheet)?;
                } else {
                    write_event(&mut writer, Event::Start(event))?;
                }
            }
            Event::Empty(event) if local_name(event.name().as_ref()) == b"c" => {
                let reference = optional_attribute(&event, b"r", sheet)?;
                if let Some(reference) = reference.filter(|reference| cells.contains_key(reference))
                {
                    let value =
                        cells
                            .get(&reference)
                            .ok_or_else(|| ExportWorkbookError::MissingCell {
                                sheet: sheet.to_owned(),
                                cell: reference.clone(),
                            })?;
                    write_cell(&mut writer, &event, value)?;
                    let _ = found.insert(reference);
                } else {
                    write_event(&mut writer, Event::Empty(event))?;
                }
            }
            Event::Eof => break,
            event => write_event(&mut writer, event)?,
        }
        buffer.clear();
    }
    if !sheet_data {
        return Err(ExportWorkbookError::MissingSheetData {
            sheet: sheet.to_owned(),
        });
    }
    if let Some(reference) = cells.keys().find(|reference| !found.contains(*reference)) {
        return Err(ExportWorkbookError::MissingCell {
            sheet: sheet.to_owned(),
            cell: reference.clone(),
        });
    }
    Ok(writer.into_inner())
}

fn write_cell(
    writer: &mut Writer<Vec<u8>>,
    original: &BytesStart<'_>,
    value: &CellValue,
) -> Result<(), ExportWorkbookError> {
    let mut start = start_without_attributes(original, &[b"t"], "cell")?;
    if matches!(value, CellValue::Text(_)) {
        start.push_attribute((b"t".as_slice(), b"inlineStr".as_slice()));
    }
    write_event(writer, Event::Start(start))?;
    match value {
        CellValue::Clear => {}
        CellValue::Text(value) => {
            let mut text = BytesStart::new("t");
            text.push_attribute((b"xml:space".as_slice(), b"preserve".as_slice()));
            write_event(writer, Event::Start(BytesStart::new("is")))?;
            write_event(writer, Event::Start(text))?;
            write_event(writer, Event::Text(BytesText::new(value)))?;
            write_event(writer, Event::End(BytesEnd::new("t")))?;
            write_event(writer, Event::End(BytesEnd::new("is")))?;
        }
        CellValue::Number(value) => {
            write_event(writer, Event::Start(BytesStart::new("v")))?;
            write_event(writer, Event::Text(BytesText::new(value)))?;
            write_event(writer, Event::End(BytesEnd::new("v")))?;
        }
    }
    write_event(writer, Event::End(BytesEnd::new("c")))
}

fn mutate_workbook(data: &[u8]) -> Result<Vec<u8>, ExportWorkbookError> {
    let part = "xl/workbook.xml";
    let mut reader = xml_reader(data);
    let mut writer = Writer::new(Vec::with_capacity(data.len()));
    let mut buffer = Vec::new();
    let mut calculation_seen = false;
    loop {
        let event = read_event(&mut reader, &mut buffer, part)?;
        match event {
            Event::Start(event) if local_name(event.name().as_ref()) == b"calcPr" => {
                calculation_seen = true;
                write_event(&mut writer, Event::Start(calculation_start(&event)?))?;
            }
            Event::Empty(event) if local_name(event.name().as_ref()) == b"calcPr" => {
                calculation_seen = true;
                write_event(&mut writer, Event::Empty(calculation_start(&event)?))?;
            }
            Event::End(event) if local_name(event.name().as_ref()) == b"workbook" => {
                if !calculation_seen {
                    write_event(&mut writer, Event::Empty(calculation_start_empty()))?;
                }
                write_event(&mut writer, Event::End(event))?;
            }
            Event::Eof => break,
            event => write_event(&mut writer, event)?,
        }
        buffer.clear();
    }
    Ok(writer.into_inner())
}

fn calculation_start(
    original: &BytesStart<'_>,
) -> Result<BytesStart<'static>, ExportWorkbookError> {
    let mut start = start_without_attributes(
        original,
        &[b"calcMode", b"fullCalcOnLoad", b"forceFullCalc"],
        "calcPr",
    )?;
    for (key, value) in [
        (b"calcMode".as_slice(), b"auto".as_slice()),
        (b"fullCalcOnLoad".as_slice(), b"1".as_slice()),
        (b"forceFullCalc".as_slice(), b"1".as_slice()),
    ] {
        start.push_attribute((key, value));
    }
    Ok(start)
}

fn calculation_start_empty() -> BytesStart<'static> {
    let mut start = BytesStart::new("calcPr");
    for (key, value) in [
        (b"calcMode".as_slice(), b"auto".as_slice()),
        (b"fullCalcOnLoad".as_slice(), b"1".as_slice()),
        (b"forceFullCalc".as_slice(), b"1".as_slice()),
    ] {
        start.push_attribute((key, value));
    }
    start
}

fn start_without_attributes(
    original: &BytesStart<'_>,
    removed: &[&[u8]],
    part: &str,
) -> Result<BytesStart<'static>, ExportWorkbookError> {
    let original_name = original.name();
    let name = std::str::from_utf8(original_name.as_ref()).map_err(|error| {
        ExportWorkbookError::XmlAttribute {
            part: part.to_owned(),
            detail: error.to_string(),
        }
    })?;
    let mut start = BytesStart::new(name.to_owned());
    for attribute in original.attributes().with_checks(false) {
        let attribute = attribute.map_err(|error| ExportWorkbookError::XmlAttribute {
            part: part.to_owned(),
            detail: error.to_string(),
        })?;
        if !removed
            .iter()
            .any(|candidate| attribute.key.as_ref() == *candidate)
        {
            start.push_attribute((attribute.key.as_ref(), attribute.value.as_ref()));
        }
    }
    Ok(start)
}

fn skip_element<R: BufRead>(
    reader: &mut Reader<R>,
    buffer: &mut Vec<u8>,
    part: &str,
) -> Result<(), ExportWorkbookError> {
    let mut depth = 1_u32;
    loop {
        buffer.clear();
        match read_event(reader, buffer, part)? {
            Event::Start(_) => {
                depth = depth
                    .checked_add(1)
                    .ok_or_else(|| ExportWorkbookError::XmlAttribute {
                        part: part.to_owned(),
                        detail: "XML nesting is too deep".into(),
                    })?;
            }
            Event::End(_) => {
                depth = depth
                    .checked_sub(1)
                    .ok_or_else(|| ExportWorkbookError::XmlAttribute {
                        part: part.to_owned(),
                        detail: "unbalanced XML cell element".into(),
                    })?;
                if depth == 0 {
                    return Ok(());
                }
            }
            Event::Eof => {
                return Err(ExportWorkbookError::XmlAttribute {
                    part: part.to_owned(),
                    detail: "unexpected end of XML in cell".into(),
                });
            }
            _ => {}
        }
    }
}

fn xml_reader(data: &[u8]) -> Reader<Cursor<&[u8]>> {
    let mut reader = Reader::from_reader(Cursor::new(data));
    reader.config_mut().trim_text(false);
    reader
}

fn read_event<'a, R: BufRead>(
    reader: &mut Reader<R>,
    buffer: &'a mut Vec<u8>,
    part: &str,
) -> Result<Event<'a>, ExportWorkbookError> {
    reader
        .read_event_into(buffer)
        .map_err(|source| ExportWorkbookError::XmlParse {
            part: part.to_owned(),
            source,
        })
}

fn write_event(writer: &mut Writer<Vec<u8>>, event: Event<'_>) -> Result<(), ExportWorkbookError> {
    writer
        .write_event(event)
        .map_err(|source| ExportWorkbookError::TemporaryWrite {
            path: PathBuf::from("OOXML XML"),
            source,
        })
}

fn required_attribute(
    event: &BytesStart<'_>,
    name: &[u8],
    part: &str,
) -> Result<String, ExportWorkbookError> {
    optional_attribute(event, name, part)?.ok_or_else(|| ExportWorkbookError::XmlAttribute {
        part: part.to_owned(),
        detail: format!("missing {} attribute", String::from_utf8_lossy(name)),
    })
}

fn optional_attribute(
    event: &BytesStart<'_>,
    name: &[u8],
    part: &str,
) -> Result<Option<String>, ExportWorkbookError> {
    for attribute in event.attributes().with_checks(false) {
        let attribute = attribute.map_err(|error| ExportWorkbookError::XmlAttribute {
            part: part.to_owned(),
            detail: error.to_string(),
        })?;
        if local_name(attribute.key.as_ref()) == name {
            return String::from_utf8(attribute.value.into_owned())
                .map(Some)
                .map_err(|error| ExportWorkbookError::XmlAttribute {
                    part: part.to_owned(),
                    detail: error.to_string(),
                });
        }
    }
    Ok(None)
}

fn local_name(name: &[u8]) -> &[u8] {
    name.rsplit(|byte| *byte == b':').next().unwrap_or(name)
}

fn read_part(archive: &mut ZipArchive<File>, part: &str) -> Result<Vec<u8>, ExportWorkbookError> {
    let mut entry = archive
        .by_name(part)
        .map_err(|_| ExportWorkbookError::MissingPart {
            part: part.to_owned(),
        })?;
    let mut data = Vec::new();
    entry
        .read_to_end(&mut data)
        .map_err(|source| ExportWorkbookError::TemporaryWrite {
            path: PathBuf::from(part),
            source,
        })?;
    Ok(data)
}

fn replace_legacy_image_slots(
    archive: &mut ZipArchive<File>,
    fallback_image: &Path,
    line_count: usize,
    manifest: &TemplateManifest,
    mutations: &mut BTreeMap<String, Vec<u8>>,
) -> Result<(), ExportWorkbookError> {
    if line_count == 0
        || !manifest
            .image_slots
            .iter()
            .any(|slot| slot.line_index < line_count)
    {
        return Ok(());
    }
    let fallback = fs::read(fallback_image).map_err(|source| ExportWorkbookError::SourceRead {
        path: fallback_image.to_path_buf(),
        source,
    })?;
    for slot in &manifest.image_slots {
        if slot.line_index < line_count {
            let _ = read_part(archive, &slot.media_path)?;
            let _ = mutations.insert(slot.media_path.clone(), fallback.clone());
        }
    }
    Ok(())
}

fn write_temporary(
    path: &Path,
    write: impl FnOnce(&mut File) -> Result<(), ExportWorkbookError>,
) -> Result<(), ExportWorkbookError> {
    let mut temporary = match OpenOptions::new().write(true).create_new(true).open(path) {
        Ok(file) => file,
        Err(source) if source.kind() == ErrorKind::AlreadyExists => {
            return Err(ExportWorkbookError::TemporaryExists {
                path: path.to_path_buf(),
            });
        }
        Err(source) => {
            return Err(ExportWorkbookError::TemporaryCreate {
                path: path.to_path_buf(),
                source,
            });
        }
    };
    let write_result = write(&mut temporary).and_then(|()| {
        temporary
            .sync_all()
            .map_err(|source| ExportWorkbookError::TemporarySync {
                path: path.to_path_buf(),
                source,
            })
    });
    drop(temporary);
    match write_result {
        Ok(()) => Ok(()),
        Err(error) => cleanup_temporary(path, error),
    }
}

fn write_archive(
    source: &Path,
    destination: &mut File,
    mutations: &BTreeMap<String, Vec<u8>>,
) -> Result<(), ExportWorkbookError> {
    let source_file =
        File::open(source).map_err(|source_error| ExportWorkbookError::SourceRead {
            path: source.to_path_buf(),
            source: source_error,
        })?;
    let mut archive = ZipArchive::new(source_file).map_err(|source_error| {
        ExportWorkbookError::InvalidArchive {
            path: source.to_path_buf(),
            source: source_error,
        }
    })?;
    let mut writer = ZipWriter::new(destination);
    let options = SimpleFileOptions::default()
        .compression_method(CompressionMethod::Deflated)
        .compression_level(Some(6))
        .last_modified_time(DateTime::default())
        .unix_permissions(0o644);
    for index in 0..archive.len() {
        let entry =
            archive
                .by_index(index)
                .map_err(|zip_error| ExportWorkbookError::InvalidArchive {
                    path: source.to_path_buf(),
                    source: zip_error,
                })?;
        let name = entry.name().to_owned();
        if let Some(replacement) = mutations.get(&name) {
            writer.start_file(&name, options).map_err(zip_write_error)?;
            writer.write_all(replacement).map_err(|source| {
                ExportWorkbookError::TemporaryWrite {
                    path: PathBuf::from("OOXML archive"),
                    source,
                }
            })?;
        } else {
            writer.raw_copy_file(entry).map_err(zip_write_error)?;
        }
    }
    let _ = writer.finish().map_err(zip_write_error)?;
    Ok(())
}

fn zip_write_error(source: ZipError) -> ExportWorkbookError {
    ExportWorkbookError::TemporaryWrite {
        path: PathBuf::from("OOXML archive"),
        source: io::Error::other(source),
    }
}

fn publish_temporary(temporary: &Path, destination: &Path) -> Result<(), ExportWorkbookError> {
    match fs::rename(temporary, destination) {
        Ok(()) => Ok(()),
        Err(source) => cleanup_temporary(
            temporary,
            ExportWorkbookError::Publish {
                temporary: temporary.to_path_buf(),
                destination: destination.to_path_buf(),
                source,
            },
        ),
    }
}

fn cleanup_temporary(
    path: &Path,
    export_error: ExportWorkbookError,
) -> Result<(), ExportWorkbookError> {
    match fs::remove_file(path) {
        Ok(()) => Err(export_error),
        Err(source) if source.kind() == ErrorKind::NotFound => Err(export_error),
        Err(source) => Err(ExportWorkbookError::TemporaryCleanup {
            path: path.to_path_buf(),
            source,
        }),
    }
}
