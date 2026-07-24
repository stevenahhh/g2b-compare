(() => {
  const workspace = document.querySelector(".catalog-workspace");
  const region = document.querySelector(".catalog-scroll-region");
  const list = document.querySelector(".catalog-results");
  const loader = document.querySelector(".catalog-loader");
  const count = document.querySelector(".result-count");
  const panel = document.querySelector(".catalog-options-panel");
  const optionContent = document.querySelector(".catalog-options-content");
  let optionRequest = 0;
  let optionObserver;

  const observeOptionPages = (productId, params, requestId) => {
    const optionLoader = optionContent?.querySelector(".option-loader");
    if (!optionLoader || !("IntersectionObserver" in window)) return;
    optionObserver?.disconnect();
    optionObserver = new IntersectionObserver(async ([entry]) => {
      const nextPage = Number(optionLoader.dataset.nextPage) || 0;
      if (!entry.isIntersecting || !nextPage) return;
      optionObserver.disconnect();
      optionLoader.textContent = "다음 옵션 불러오는 중…";
      params.set("page", String(nextPage));
      try {
        const response = await fetch(
          `/catalog/products/${encodeURIComponent(productId)}/options?${params}`,
        );
        if (!response.ok) throw new Error(String(response.status));
        const fragment = document.createElement("template");
        fragment.innerHTML = await response.text();
        optionLoader.before(fragment.content);
        const following = Number(
          response.headers.get("X-Catalog-Options-Next-Page"),
        );
        if (!following || requestId !== optionRequest) {
          optionLoader.remove();
          return;
        }
        optionLoader.dataset.nextPage = String(following);
        optionLoader.textContent = "아래로 스크롤하면 다음 옵션을 불러옴";
        optionObserver.observe(optionLoader);
      } catch {
        optionLoader.textContent = "옵션을 더 불러오지 못함. 다시 스크롤하면 재시도함";
        optionObserver.observe(optionLoader);
      }
    }, { root: optionContent, rootMargin: "400px 0px" });
    optionObserver.observe(optionLoader);
  };

  const openOptions = async (card) => {
    if (!card || !panel || !optionContent || !workspace) return;
    const productId = card.dataset.parentProductId;
    if (!productId) return;
    const requestId = ++optionRequest;
    workspace.classList.add("has-options");
    panel.hidden = false;
    panel.setAttribute("aria-busy", "true");
    optionContent.textContent = "하위 옵션 불러오는 중…";
    document.querySelectorAll("[data-main-product]").forEach((card) => {
      card.classList.toggle("is-selected", card.dataset.mainProduct === productId);
    });
    const params = new URLSearchParams();
    const estimateId = new URLSearchParams(window.location.search).get("estimate_id");
    if (estimateId) params.set("estimate_id", estimateId);
    try {
      const response = await fetch(
        `/catalog/products/${encodeURIComponent(productId)}/options?${params}`,
      );
      if (!response.ok) throw new Error(String(response.status));
      const html = await response.text();
      if (requestId === optionRequest) {
        optionContent.innerHTML = html;
        observeOptionPages(productId, params, requestId);
      }
    } catch {
      if (requestId === optionRequest) {
        optionContent.textContent = "하위 옵션을 불러오지 못함";
      }
    } finally {
      if (requestId === optionRequest) panel.removeAttribute("aria-busy");
    }
  };

  list?.addEventListener("click", (event) => {
    if (event.target.closest("a, button, form, input")) return;
    void openOptions(event.target.closest("[data-parent-product-id]"));
  });

  list?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest("[data-parent-product-id]");
    if (!card || event.target !== card) return;
    event.preventDefault();
    void openOptions(card);
  });

  document.querySelector(".option-panel-close")?.addEventListener("click", () => {
    optionRequest += 1;
    optionObserver?.disconnect();
    panel.hidden = true;
    workspace?.classList.remove("has-options");
    document.querySelectorAll("[data-main-product]").forEach((card) => {
      card.classList.remove("is-selected");
    });
  });

  if (!region || !list || !loader || !("IntersectionObserver" in window)) return;
  document.documentElement.classList.add("catalog-enhanced");
  let nextPage = Number(loader.dataset.nextPage) || 0;
  let loading = false;

  const observer = new IntersectionObserver(async ([entry]) => {
    if (!entry.isIntersecting || loading || !nextPage) return;
    loading = true;
    loader.textContent = "다음 결과 불러오는 중…";
    const params = new URLSearchParams(window.location.search);
    params.set("page", String(nextPage));
    try {
      const response = await fetch(`/catalog/items?${params.toString()}`);
      if (!response.ok) throw new Error(String(response.status));
      const fragment = document.createElement("template");
      fragment.innerHTML = await response.text();
      list.append(fragment.content);
      nextPage = Number(response.headers.get("X-Catalog-Next-Page")) || 0;
      loader.dataset.nextPage = nextPage ? String(nextPage) : "";
      const total = Number(count?.dataset.totalCount) || list.children.length;
      if (count) {
        count.textContent = `본품 검색 결과 ${total}건 · 현재 ${list.children.length}건 표시`;
      }
      loader.textContent = nextPage
        ? "아래로 스크롤하면 다음 결과를 불러옴"
        : "모든 결과를 불러옴";
    } catch {
      loader.textContent = "추가 결과를 불러오지 못함. 다시 스크롤하면 재시도함";
    } finally {
      loading = false;
    }
  }, { root: region, rootMargin: "600px 0px" });

  if (nextPage) observer.observe(loader);
})();
