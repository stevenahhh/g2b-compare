<script>
  import {
    conciseSpec,
    documentItemName,
    documentUnit,
  } from "../../lib/spec.js";
  import {
    appliedPrice,
    comparisonAttributes,
    comparisonFor,
    comparisonSpec,
    rowAttributes,
  } from "./comparison.js";
  import { compactCompanyName, money } from "./formatting.js";
  import { closeOnEscape } from "./keyboard.js";
  let {
    document,
    remote,
    line,
    index,
    details,
    busy = false,
    onRemove = () => {},
    onShowTooltip = () => {},
    onHideTooltip = () => {},
  } = $props();
  const attrs = () => rowAttributes(document, remote, line, details);
  const show = (event, spec, attributes) =>
    onShowTooltip(event, spec, attributes);
  const hide = (event) => {
    if (closeOnEscape(event.key)) onHideTooltip();
  };
</script>

<tr
  ><td class="document-sequence document-no-copy"
    ><span>{index + 1}</span><button
      class="button--secondary"
      type="button"
      aria-label={`${line.item_name_snapshot} 행 삭제`}
      disabled={busy}
      onclick={() => onRemove(line.id)}>삭제</button
    ></td
  ><td>{documentItemName(line.item_name_snapshot, line.spec_snapshot)}</td><td
    ><button
      type="button"
      class="spec-tooltip-trigger"
      aria-label={`${conciseSpec(line.spec_snapshot, attrs(), line.item_name_snapshot)}. 전체 규격: ${line.spec_snapshot}`}
      onpointerenter={(event) => show(event, line.spec_snapshot, attrs())}
      onpointerleave={onHideTooltip}
      onfocus={(event) => show(event, line.spec_snapshot, attrs())}
      onblur={onHideTooltip}
      onkeydown={hide}
      >{conciseSpec(
        line.spec_snapshot,
        attrs(),
        line.item_name_snapshot,
      )}</button
    ></td
  ><td class="document-center"
    >{documentUnit(
      line.item_name_snapshot,
      line.unit_snapshot,
      line.spec_snapshot,
    )}</td
  ><td class="document-number">{money(appliedPrice(line, details))}</td>
  {#each ["A", "B", "C"] as slot}{@const comparison = comparisonFor(
      details,
      slot,
    )}<td class:document-baseline={slot === "A"}
      >{#if comparison}{compactCompanyName(
          comparison.company_snapshot,
        )}{:else if busy}<span
          class="loading-placeholder loading-placeholder--short"
          aria-hidden="true"
        ></span>{/if}</td
    ><td class:document-baseline={slot === "A"}
      >{#if comparison}<button
          type="button"
          class="spec-tooltip-trigger"
          aria-label={`${comparisonSpec(document, remote, comparison, line, details)}. 전체 규격: ${comparison.spec_snapshot}`}
          onpointerenter={(event) =>
            show(
              event,
              comparison.spec_snapshot,
              comparisonAttributes(document, remote, comparison, line, details),
            )}
          onpointerleave={onHideTooltip}
          onfocus={(event) =>
            show(
              event,
              comparison.spec_snapshot,
              comparisonAttributes(document, remote, comparison, line, details),
            )}
          onblur={onHideTooltip}
          onkeydown={hide}
          >{comparisonSpec(document, remote, comparison, line, details)}</button
        >{:else if busy}<span
          class="loading-placeholder loading-placeholder--text"
          aria-hidden="true"
        ></span>{/if}</td
    ><td class:document-baseline={slot === "A"}
      >{#if comparison}<a
          class="document-product-link"
          href={comparison.g2b_url}
          target="_blank"
          rel="noreferrer"
          aria-label={`${slot}사 물품식별번호 ${comparison.product_id} 나라장터에서 보기`}
          >{comparison.product_id}</a
        >{:else if busy}<span
          class="loading-placeholder loading-placeholder--short"
          aria-hidden="true"
        ></span>{/if}</td
    ><td class:document-baseline={slot === "A"} class="document-number"
      >{#if comparison}{money(
          comparison.price_won_snapshot,
        )}{:else if busy}<span
          class="loading-placeholder loading-placeholder--short"
          aria-hidden="true"
        ></span>{/if}</td
    >{/each}<td></td></tr
>
