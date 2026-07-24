import { describe, expect, it } from 'vitest';
import { mount } from 'svelte';

describe('frontend scaffold', () => {
  it('loads the installed Svelte runtime', () => {
    expect(typeof mount).toBe('function');
  });
});
