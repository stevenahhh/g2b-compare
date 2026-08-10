<script lang="ts">
  import {
    compactCompanyName,
    conciseSpec,
    documentItemName,
    documentUnit,
  } from "../comparisonFormatting";
  import type {
    ComparisonSlot,
    EstimateComparison,
    EstimateLine,
    ProductAttribute,
  } from "../models";

  type TooltipTarget = "selected" | ComparisonSlot;

  let {
    line,
    index,
    disabled = false,
    onRemove,
    tooltipDismissal = 0,
  }: {
    line: EstimateLine;
    index: number;
    disabled?: boolean;
    onRemove: (lineId: string) => void;
    tooltipDismissal?: number;
  } = $props();

  let tooltip = $state<{
    target: TooltipTarget;
    specification: string;
    attributes: ProductAttribute[];
    above: boolean;
    left: number;
    top: number;
  } | null>(null);

  function tooltipId(target: TooltipTarget): string {
    return `comparison-specification-${line.id}-${target}`;
  }

  function comparison(slot: ComparisonSlot): EstimateComparison | undefined {
    return line.comparisons.find((item) => item.slot === slot);
  }

  function lineAttributes(value: EstimateLine): ProductAttribute[] {
    const candidate = (value as EstimateLine & { attributes?: ProductAttribute[] }).attributes;
    return Array.isArray(candidate) ? candidate : [];
  }

  const attributes = $derived(lineAttributes(line));
  const itemName = $derived(documentItemName(line.item_name_snapshot, line.spec_snapshot));
  const specification = $derived(
    conciseSpec(line.spec_snapshot, attributes, line.item_name_snapshot),
  );
  const unit = $derived(
    documentUnit(line.item_name_snapshot, line.unit_snapshot, line.spec_snapshot),
  );
  const appliedPrice = $derived(
    comparison("A")?.price_won_snapshot ?? line.unit_price_won_snapshot,
  );

  function showTooltip(
    event: PointerEvent | FocusEvent,
    target: TooltipTarget,
    fullSpecification: string,
    tooltipAttributes: ProductAttribute[] = [],
  ) {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const above = rect.bottom > globalThis.innerHeight * 0.65;
    tooltip = {
      target,
      specification: fullSpecification,
      attributes: tooltipAttributes,
      above,
      left: Math.max(8, Math.min(rect.left, globalThis.innerWidth - 520)),
      top: above ? rect.top - 8 : rect.bottom + 8,
    };
  }

  function hideTooltip() {
    tooltip = null;
  }

  function hideOnEscape(event: KeyboardEvent) {
    if (event.key === "Escape") hideTooltip();
  }

  $effect(() => {
    tooltipDismissal;
    tooltip = null;
  });
</script>

<tr>
  <td class="document-sequence document-no-copy">
    <span>{index + 1}</span>
    <button
      class="button button--secondary"
      type="button"
      aria-label={`${line.item_name_snapshot} 행 삭제`}
      {disabled}
      onclick={() => onRemove(line.id)}
    >삭제</button>
  </td>
  <td>{itemName}</td>
  <td>
    <button
      type="button"
      class="spec-tooltip-trigger"
      aria-describedby={tooltip?.target === "selected" ? tooltipId("selected") : undefined}
      aria-label={`${specification}. 전체 규격: ${line.spec_snapshot}`}
      onpointerenter={(event) => showTooltip(event, "selected", line.spec_snapshot, attributes)}
      onpointerleave={hideTooltip}
      onfocus={(event) => showTooltip(event, "selected", line.spec_snapshot, attributes)}
      onblur={hideTooltip}
      onkeydown={hideOnEscape}
    >{specification}</button>
    {#if tooltip?.target === "selected"}
      <aside
        id={tooltipId("selected")}
        class:spec-tooltip--above={tooltip.above}
        class="spec-tooltip"
        style={`inset-inline-start: ${tooltip.left}px; inset-block-start: ${tooltip.top}px;`}
        role="tooltip"
      >
        <p class="spec-tooltip__title">전체 규격</p>
        <p>{tooltip.specification}</p>
        {#if tooltip.attributes.length}
          <dl>
            {#each tooltip.attributes as attribute}
              <div>
                <dt>{attribute.name}</dt>
                <dd>{attribute.value}{attribute.unit ?? ""}</dd>
              </div>
            {/each}
          </dl>
        {/if}
      </aside>
    {/if}
  </td>
  <td class="document-center">{unit}</td>
  <td class="document-number">{appliedPrice.toLocaleString()}</td>
  {#each ["A", "B", "C"] as slot}
    {@const item = comparison(slot as ComparisonSlot)}
    <td class:document-baseline={slot === "A"}>{item ? compactCompanyName(item.company_snapshot) : ""}</td>
    <td class:document-baseline={slot === "A"}>
      {#if item}
        <button
          type="button"
          class="spec-tooltip-trigger"
          aria-describedby={tooltip?.target === slot ? tooltipId(slot as ComparisonSlot) : undefined}
          aria-label={`${item.spec_snapshot}. 전체 규격: ${item.spec_snapshot}`}
          onpointerenter={(event) => showTooltip(event, slot as ComparisonSlot, item.spec_snapshot)}
          onpointerleave={hideTooltip}
          onfocus={(event) => showTooltip(event, slot as ComparisonSlot, item.spec_snapshot)}
          onblur={hideTooltip}
          onkeydown={hideOnEscape}
        >{item.spec_snapshot}</button>
        {#if tooltip?.target === slot}
          <aside
            id={tooltipId(slot as ComparisonSlot)}
            class:spec-tooltip--above={tooltip.above}
            class="spec-tooltip"
            style={`inset-inline-start: ${tooltip.left}px; inset-block-start: ${tooltip.top}px;`}
            role="tooltip"
          ><p class="spec-tooltip__title">전체 규격</p><p>{tooltip.specification}</p></aside>
        {/if}
      {/if}
    </td>
    <td class:document-baseline={slot === "A"}>
      {#if item}
        <a
          class="document-product-link"
          href={item.g2b_url}
          target="_blank"
          rel="noreferrer"
          aria-label={`${slot}사 물품식별번호 ${item.product_id} 나라장터에서 보기`}
        >{item.product_id}</a>
      {/if}
    </td>
    <td class:document-baseline={slot === "A"} class="document-number">{item ? item.price_won_snapshot.toLocaleString() : ""}</td>
  {/each}
  <td></td>
</tr>
