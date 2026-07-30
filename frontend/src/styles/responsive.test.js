import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const shellCss = readFileSync(new URL('./shell.css', import.meta.url), 'utf8');
const workspaceCss = readFileSync(new URL('./workspace.css', import.meta.url), 'utf8');
const estimateRoute = readFileSync(
  new URL('../routes/EstimateRoute.svelte', import.meta.url),
  'utf8',
);

describe('responsive workspace contract', () => {
  it('keeps the primary navigation usable on narrow screens', () => {
    expect(shellCss).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.app-header\s*\{[\s\S]*padding-inline:\s*var\(--space-3\)/,
    );
    expect(shellCss).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.app-nav\s*\{[\s\S]*overflow-x:\s*auto/,
    );
  });

  it('stacks catalog controls and balances document actions on mobile', () => {
    expect(workspaceCss).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.catalog-controls\s*\{[\s\S]*grid-template-columns:\s*1fr/,
    );
    expect(estimateRoute).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.document-catalog \.catalog-controls\s*\{[\s\S]*grid-template-columns:\s*1fr/,
    );
    expect(workspaceCss).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.page-actions\s*\{[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/,
    );
  });
});
