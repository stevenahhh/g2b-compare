import { DESIGN_CONTRACT } from "./design-contract.js";

const px = (value: number): string => `${String(value)}px`;

export function applyDesignTokens(root: HTMLElement): void {
  const { colors, interaction, layout, typography } = DESIGN_CONTRACT;
  const tokens = {
    "--background": colors.background,
    "--surface": colors.surface,
    "--text": colors.text,
    "--secondary": colors.secondary,
    "--border": colors.border,
    "--accent": colors.accent,
    "--success": colors.success,
    "--warning": colors.warning,
    "--error": colors.error,
    "--space-none": px(0),
    "--space-hairline": px(2),
    "--space-tight": px(4),
    "--space-compact": px(6),
    "--space-default": px(8),
    "--space-control": px(10),
    "--space-panel": px(12),
    "--space-section": px(16),
    "--space-wide": px(20),
    "--space-large": px(24),
    "--space-page": px(32),
    "--font-size-caption": px(11),
    "--font-size-label": px(typography.table.fontSizePx),
    "--font-size-body": px(typography.body.fontSizePx),
    "--font-size-panel-title": px(14),
    "--font-size-section-title": px(16),
    "--font-size-workspace-title": px(18),
    "--font-size-showcase-title": px(28),
    "--line-height-compact": px(16),
    "--line-height-label": px(typography.table.lineHeightPx),
    "--line-height-body": px(typography.body.lineHeightPx),
    "--line-height-heading": px(24),
    "--line-height-display": px(36),
    "--row-compact": px(layout.rowHeightsPx.compact),
    "--row-regular": px(layout.rowHeightsPx.regular),
    "--row-comfortable": px(layout.rowHeightsPx.comfortable),
    "--control-min": px(interaction.accessibility.primaryControlMinSizePx),
    "--focus-width": px(interaction.focus.outlinePx),
    "--left-wide": px(layout.viewport1440.leftRailPx),
    "--right-wide": px(layout.viewport1440.rightInspectorPx),
    "--left-narrow": px(layout.viewport1024.leftRailPx),
    "--right-overlay": px(layout.viewport1024.overlayInspectorPx)
  } as const;
  for (const [name, value] of Object.entries(tokens)) {
    root.style.setProperty(name, value);
  }
}
