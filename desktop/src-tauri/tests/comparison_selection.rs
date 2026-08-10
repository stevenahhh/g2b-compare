use std::error::Error;
use std::sync::{Arc, Barrier};
use std::thread;

use g2b_compare_desktop_lib::comparison_selection::{
    ComparisonCandidate, ComparisonSelectionError, ComparisonSelectionInput, select_comparisons,
};

fn candidate(
    product_id: &str,
    company: &str,
    price_won: i64,
    source_row: u32,
) -> ComparisonCandidate {
    ComparisonCandidate {
        product_id: product_id.into(),
        company: company.into(),
        price_won,
        source_row,
    }
}

fn input(
    selected_product_id: &str,
    selected_company: &str,
    selected_price_won: i64,
    candidates: Vec<ComparisonCandidate>,
) -> ComparisonSelectionInput {
    ComparisonSelectionInput {
        selected: candidate(selected_product_id, selected_company, selected_price_won, 1),
        candidates,
    }
}

#[test]
fn selects_deterministic_a_b_c_choices_from_shuffled_candidates() -> Result<(), Box<dyn Error>> {
    let request = input(
        "A-001",
        "선택사",
        100,
        vec![
            candidate("C-002", "C사", 150, 12),
            candidate("B-002", "B사", 120, 11),
            candidate("A-001", "선택사", 100, 1),
            candidate("B-001", "B사", 120, 10),
            candidate("C-001", "C사", 150, 9),
            candidate("저가-001", "저가사", 99, 2),
        ],
    );

    let selected = select_comparisons(request)?;

    assert_eq!(
        selected
            .iter()
            .map(|item| item.product_id.as_str())
            .collect::<Vec<_>>(),
        ["A-001", "B-001", "C-001"]
    );
    assert_eq!(
        selected
            .iter()
            .map(|item| item.company.as_str())
            .collect::<Vec<_>>(),
        ["선택사", "B사", "C사"]
    );
    Ok(())
}

#[test]
fn tie_breaks_by_source_row_then_product_id_and_never_reuses_a_candidate()
-> Result<(), Box<dyn Error>> {
    let request = input(
        "A-001",
        "선택사",
        100,
        vec![
            candidate("B-later", "B사", 120, 8),
            candidate("B-earlier", "B사", 120, 3),
            candidate("B-earlier", "B사", 120, 3),
            candidate("C-z", "C사", 130, 7),
            candidate("C-a", "C사", 130, 7),
        ],
    );

    let selected = select_comparisons(request)?;

    assert_eq!(
        selected
            .iter()
            .map(|item| (item.company.as_str(), item.product_id.as_str()))
            .collect::<Vec<_>>(),
        [("선택사", "A-001"), ("B사", "B-earlier"), ("C사", "C-a")]
    );
    assert_eq!(
        selected
            .iter()
            .map(|item| item.product_id.as_str())
            .collect::<std::collections::HashSet<_>>()
            .len(),
        3
    );
    Ok(())
}

#[test]
fn concurrent_requests_keep_each_selection_isolated() -> Result<(), Box<dyn Error>> {
    let barrier = Arc::new(Barrier::new(2));
    let first = input(
        "A-1",
        "선택사-1",
        100,
        vec![
            candidate("B-1", "B사-1", 110, 2),
            candidate("C-1", "C사-1", 120, 3),
        ],
    );
    let second = input(
        "A-2",
        "선택사-2",
        200,
        vec![
            candidate("B-2", "B사-2", 210, 2),
            candidate("C-2", "C사-2", 220, 3),
        ],
    );

    let run = |request: ComparisonSelectionInput, barrier: Arc<Barrier>| {
        thread::spawn(move || {
            barrier.wait();
            select_comparisons(request)
        })
    };
    let first_handle = run(first, Arc::clone(&barrier));
    let second_handle = run(second, barrier);
    let first_result = first_handle.join().map_err(|_| "first worker panicked")??;
    let second_result = second_handle
        .join()
        .map_err(|_| "second worker panicked")??;

    assert_eq!(first_result[0].product_id, "A-1");
    assert_eq!(first_result[1].product_id, "B-1");
    assert_eq!(first_result[2].product_id, "C-1");
    assert_eq!(second_result[0].product_id, "A-2");
    assert_eq!(second_result[1].product_id, "B-2");
    assert_eq!(second_result[2].product_id, "C-2");
    Ok(())
}

#[test]
fn rejects_malformed_inputs_before_selection() {
    let cases = [
        input(
            "",
            "선택사",
            100,
            vec![
                candidate("B-1", "B사", 110, 2),
                candidate("C-1", "C사", 120, 3),
            ],
        ),
        input(
            "A-1",
            "선택사",
            -1,
            vec![
                candidate("B-1", "B사", 110, 2),
                candidate("C-1", "C사", 120, 3),
            ],
        ),
        input(
            "A-1",
            "선택사",
            100,
            vec![
                candidate("B-1", "", 110, 2),
                candidate("C-1", "C사", 120, 3),
            ],
        ),
        input(
            "A-1",
            "선택사",
            100,
            vec![
                candidate("B-1", "B사", 110, 0),
                candidate("C-1", "C사", 120, 3),
            ],
        ),
    ];

    for request in cases {
        assert!(matches!(
            select_comparisons(request),
            Err(ComparisonSelectionError::MalformedInput(_))
        ));
    }
}
