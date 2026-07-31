export const KOREANET = "주식회사 코리아넷";

async function cached(getCatalogCache, key, onCached) {
  const value = await getCatalogCache(key).catch(() => null);
  if (value) onCached(value);
  return value;
}
async function saveCache(putCatalogCache, key, value) {
  try {
    await putCatalogCache(key, value);
  } catch {}
}

export async function loadDocumentProducts(
  query,
  sort,
  dependencies,
  onCached = () => {},
) {
  const { getCatalogCache, putCatalogCache, requestJson } = dependencies;
  const key = `document-products:v4:${query}:${sort}`;
  const cachedResult = await cached(getCatalogCache, key, onCached);
  const parameters = `preferred_company_name=${encodeURIComponent(KOREANET)}&q=${encodeURIComponent(query)}&sort=${sort}&page=1&page_size=100`;
  const result = await requestJson(`/api/catalog/products?${parameters}`);
  await saveCache(putCatalogCache, key, result);
  return { cached: cachedResult, result };
}

export async function loadDocumentOptions(
  item,
  dependencies,
  onCached = () => {},
) {
  const { getCatalogCache, putCatalogCache, requestJson } = dependencies;
  const key = `document-product-options:v2:${item.product_id}`;
  const cachedResult = await cached(getCatalogCache, key, onCached);
  const first = await requestJson(
    `/api/catalog/products/${item.product_id}/options?page=1&page_size=100`,
  );
  const rest = await Promise.all(
    Array.from({ length: first.page_count - 1 }, (_, index) =>
      requestJson(
        `/api/catalog/products/${item.product_id}/options?page=${index + 2}&page_size=100`,
      ),
    ),
  );
  const result = {
    ...first,
    items: [...first.items, ...rest.flatMap((page) => page.items)],
  };
  await saveCache(putCatalogCache, key, result);
  return { cached: cachedResult, result };
}
