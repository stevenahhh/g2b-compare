export function element<K extends keyof HTMLElementTagNameMap>(
  tagName: K,
  options: {
    readonly className?: string;
    readonly text?: string;
    readonly attributes?: Readonly<Record<string, string>>;
    readonly children?: readonly (Node | string)[];
  } = {}
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tagName);
  if (options.className !== undefined) {
    node.className = options.className;
  }
  if (options.text !== undefined) {
    node.textContent = options.text;
  }
  for (const [name, value] of Object.entries(options.attributes ?? {})) {
    node.setAttribute(name, value);
  }
  for (const child of options.children ?? []) {
    node.append(child);
  }
  return node;
}
