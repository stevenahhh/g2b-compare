"""Batch-load option candidates for coherent bundle ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.db.sql import as_int, as_text, query

from .estimate_models import ComparisonView, MainCandidate, OptionCandidate
from .estimate_text import parse_option_label, text_or

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True)
class BundleOptionPools:
    """All verified group and company options loaded for one refresh."""

    group_by_product: dict[str, str]
    by_group: dict[str, tuple[OptionCandidate, ...]]
    by_company: dict[str, tuple[OptionCandidate, ...]]

    def cache_key(self, main: MainCandidate) -> tuple[str, str]:
        """Return the option-equivalence key for one main product."""
        return (
            self.group_by_product.get(main.view.product_id, ""),
            main.view.company,
        )

    def candidates(self, main: MainCandidate) -> tuple[OptionCandidate, ...]:
        """Return group-first candidates with duplicate relations removed."""
        candidates = (
            *self.by_group.get(
                self.group_by_product.get(main.view.product_id, ""),
                (),
            ),
            *self.by_company.get(main.view.company, ()),
        )
        result: list[OptionCandidate] = []
        seen: set[tuple[str, str | None, int]] = set()
        for candidate in candidates:
            identity = (
                candidate.view.product_id,
                candidate.view.relation_id,
                candidate.view.price_won,
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(candidate)
        return tuple(result)

    def group_candidates(
        self,
        main: MainCandidate,
    ) -> tuple[OptionCandidate, ...]:
        """Return only options verified in the main product's contract group."""
        return tuple(
            candidate
            for candidate in self.by_group.get(
                self.group_by_product.get(main.view.product_id, ""),
                (),
            )
            if candidate.view.company == main.view.company
        )

    def company_candidates(
        self,
        main: MainCandidate,
    ) -> tuple[OptionCandidate, ...]:
        """Return same-company options used only after group matching fails."""
        return self.by_company.get(main.view.company, ())

    def all_candidates(self) -> tuple[OptionCandidate, ...]:
        """Return every company option once for global row comparison."""
        result: list[OptionCandidate] = []
        seen: set[tuple[str, str, str | None, int]] = set()
        for candidates in self.by_company.values():
            for candidate in candidates:
                identity = (
                    candidate.view.company,
                    candidate.view.product_id,
                    candidate.view.relation_id,
                    candidate.view.price_won,
                )
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(candidate)
        return tuple(result)


def load_bundle_option_pools(
    connection: sqlite3.Connection,
) -> BundleOptionPools:
    """Load every option relation in three bounded queries."""
    group_by_product = {
        as_text(row[0]): as_text(row[1])
        for row in query(
            connection,
            """
            SELECT product_id, contract_group
            FROM priority_product_contract_groups
            """,
        ).fetchall()
    }
    by_group: dict[str, list[OptionCandidate]] = {}
    group_relations: dict[str, set[str]] = {}
    for row in query(
        connection,
        """
        SELECT relation.contract_group, relation.relation_id,
        relation.option_product_id, relation.company_name,
        relation.raw_label, relation.relation_price_won,
        MIN(relation.position) OVER (
            PARTITION BY relation.contract_group, relation.option_product_id
        ),
        option.item_name, option.spec, option.details
        FROM priority_contract_options AS relation
        LEFT JOIN priority_options AS option
        ON option.company_name = relation.company_name
        AND option.product_id = relation.option_product_id
        AND option.price_won = relation.relation_price_won
        WHERE relation.active = 1
        ORDER BY relation.contract_group, relation.position, option.source_row
        """,
    ).fetchall():
        contract_group = as_text(row[0])
        relation_id = as_text(row[1])
        seen_relations = group_relations.setdefault(contract_group, set())
        if relation_id in seen_relations:
            continue
        seen_relations.add(relation_id)
        raw_label = as_text(row[4])
        parsed_item, parsed_spec = parse_option_label(raw_label)
        item_name = text_or(row[7], parsed_item)
        spec = text_or(row[8], parsed_spec)
        details = text_or(row[9], "")
        by_group.setdefault(contract_group, []).append(
            OptionCandidate(
                ComparisonView(
                    "",
                    as_text(row[2]),
                    relation_id,
                    as_text(row[3]),
                    spec,
                    as_int(row[5]),
                ),
                item_name,
                f"{raw_label} {spec} {details}",
                0,
                as_int(row[6]),
            )
        )
    by_company: dict[str, list[OptionCandidate]] = {}
    for row in query(
        connection,
        """
        SELECT company_name, product_id, item_name, spec, price_won, details,
        source_row
        FROM priority_options ORDER BY company_name, source_row
        """,
    ).fetchall():
        company = as_text(row[0])
        by_company.setdefault(company, []).append(
            OptionCandidate(
                ComparisonView(
                    "",
                    as_text(row[1]),
                    None,
                    company,
                    as_text(row[3]),
                    as_int(row[4]),
                ),
                as_text(row[2]),
                f"{as_text(row[3])} {as_text(row[5])}",
                1,
                as_int(row[6]),
            )
        )
    for row in query(
        connection,
        """
        SELECT company_name, relation_id, option_product_id,
        raw_label, relation_price_won,
        MIN(position) OVER (
            PARTITION BY company_name, option_product_id
        )
        FROM priority_contract_options
        WHERE active = 1 ORDER BY company_name, position
        """,
    ).fetchall():
        company = as_text(row[0])
        item_name, spec = parse_option_label(as_text(row[3]))
        by_company.setdefault(company, []).append(
            OptionCandidate(
                ComparisonView(
                    "",
                    as_text(row[2]),
                    as_text(row[1]),
                    company,
                    spec,
                    as_int(row[4]),
                ),
                item_name,
                spec,
                1,
                as_int(row[5]),
            )
        )
    return BundleOptionPools(
        group_by_product,
        {key: tuple(value) for key, value in by_group.items()},
        {key: tuple(value) for key, value in by_company.items()},
    )
