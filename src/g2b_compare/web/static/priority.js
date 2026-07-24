(() => {
  const ROW_HEIGHT = 56;
  // DOM ceiling: at most 60 rendered .line-item rows.
  const WINDOW_SIZE = 60;
  const OVERSCAN_ROWS = 8;
  const THEME_KEY = "g2b-theme";
  const root = document.documentElement;
  const readTheme = () => {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch {
      return null;
    }
  };
  const writeTheme = (theme) => {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Storage may be disabled by browser privacy settings.
    }
  };
  const savedTheme = readTheme();

  root.dataset.theme = savedTheme === "dark" ? "dark" : "light";

  const themeToggle = document.querySelector("[data-theme-toggle]");
  const setTheme = (theme) => {
    root.dataset.theme = theme;
    writeTheme(theme);
    if (themeToggle) {
      themeToggle.textContent = theme === "dark" ? "라이트 모드" : "다크 모드";
      themeToggle.setAttribute("aria-pressed", String(theme === "dark"));
    }
  };
  setTheme(root.dataset.theme);
  themeToggle?.addEventListener("click", () => {
    setTheme(root.dataset.theme === "dark" ? "light" : "dark");
  });

  const form = document.querySelector(".priority-search-panel");
  const input = form?.querySelector("input[name=q]");
  const scrollRegion = document.querySelector(".priority-virtual-scroll");
  const body = document.querySelector(".priority-results-body");
  const topSpacer = document.querySelector(".priority-spacer-top");
  const bottomSpacer = document.querySelector(".priority-spacer-bottom");
  const loader = document.querySelector(".priority-loader");
  const pageCount = Number(scrollRegion?.dataset.pageCount) || 1;
  const initialPage = Number(scrollRegion?.dataset.page) || 1;
  const loadedItems = body
    ? Array.from(body.querySelectorAll(".line-item"))
    : [];
  let nextPage = initialPage + 1;
  let loading = false;
  let renderedStart = -1;
  let renderedEnd = -1;
  let searchTerm = input?.value.trim() || "";

  if (!form || !input || !scrollRegion || !body || !topSpacer || !bottomSpacer || !loader) return;

  const spacerHeight = (spacer, rows) => {
    spacer.firstElementChild.firstElementChild.style.height =
      `${Math.max(0, rows * ROW_HEIGHT)}px`;
  };

  const highlightMatches = (row) => {
    row.querySelectorAll("mark.search-highlight").forEach((mark) => {
      mark.replaceWith(document.createTextNode(mark.textContent));
    });
    row.normalize();
    if (!searchTerm) return;

    const normalizedTerm = searchTerm.toLocaleLowerCase();
    const walker = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
    const matches = [];
    let node;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue;
      const lowerText = text.toLocaleLowerCase();
      let index = lowerText.indexOf(normalizedTerm);
      if (index === -1) continue;
      matches.push([node, text, lowerText]);
    }
    matches.forEach(([textNode, text, lowerText]) => {
      const fragment = document.createDocumentFragment();
      let start = 0;
      let index = lowerText.indexOf(normalizedTerm, start);
      while (index !== -1) {
        fragment.append(document.createTextNode(text.slice(start, index)));
        const mark = document.createElement("mark");
        mark.className = "search-highlight";
        mark.textContent = text.slice(index, index + searchTerm.length);
        fragment.append(mark);
        start = index + searchTerm.length;
        index = lowerText.indexOf(normalizedTerm, start);
      }
      fragment.append(document.createTextNode(text.slice(start)));
      textNode.replaceWith(fragment);
    });
  };

  const renderWindow = () => {
    const firstVisible = Math.floor(scrollRegion.scrollTop / ROW_HEIGHT);
    const start = Math.max(0, firstVisible - OVERSCAN_ROWS);
    const end = Math.min(loadedItems.length, start + WINDOW_SIZE);
    if (start === renderedStart && end === renderedEnd) return;

    const fragment = document.createDocumentFragment();
    loadedItems.slice(start, end).forEach((row) => {
      highlightMatches(row);
      fragment.append(row);
    });
    body.replaceChildren(fragment);
    spacerHeight(topSpacer, start);
    spacerHeight(bottomSpacer, loadedItems.length - end);
    renderedStart = start;
    renderedEnd = end;
  };

  const fetchPageRows = async (page) => {
    const response = await fetch(`/priority?page=${page}`);
    if (!response.ok) throw new Error(String(response.status));
    const documentPage = new DOMParser().parseFromString(
      await response.text(),
      "text/html",
    );
    const rows = Array.from(documentPage.querySelectorAll(".line-item"));
    if (rows.length === 0) throw new Error("empty priority page");
    return rows;
  };

  const loadNextPage = async () => {
    if (loading || nextPage > pageCount) return;
    loading = true;
    loader.textContent = "다음 결과 불러오는 중…";
    try {
      const rows = await fetchPageRows(nextPage);
      loadedItems.push(...rows);
      nextPage += 1;
      renderedStart = -1;
      renderWindow();
      loader.textContent = nextPage <= pageCount
        ? "아래로 스크롤하면 다음 결과를 불러옴"
        : "모든 결과를 불러옴";
    } catch {
      loader.textContent = "추가 결과를 불러오지 못함. 다시 스크롤하면 재시도함";
    } finally {
      loading = false;
    }
  };

  const loadPreviousPages = async () => {
    if (initialPage <= 1) return;
    loading = true;
    loader.textContent = "이전 결과 불러오는 중…";
    try {
      const previousRows = [];
      for (let page = 1; page < initialPage; page += 1) {
        previousRows.push(...await fetchPageRows(page));
      }
      loadedItems.unshift(...previousRows);
      renderedStart = -1;
      renderWindow();
      loader.textContent = nextPage <= pageCount
        ? "아래로 스크롤하면 다음 결과를 불러옴"
        : "모든 결과를 불러옴";
    } catch {
      loader.textContent = "이전 결과를 불러오지 못함";
    } finally {
      loading = false;
    }
  };

  const maybeLoadNextPage = () => {
    renderWindow();
    const nearBottom =
      scrollRegion.scrollTop + scrollRegion.clientHeight >=
      scrollRegion.scrollHeight - ROW_HEIGHT * 8;
    if (nearBottom) {
      void loadNextPage();
    }
  };

  form.addEventListener("submit", (event) => event.preventDefault());
  input.addEventListener("input", () => {
    searchTerm = input.value.trim();
    renderedStart = -1;
    renderWindow();
  });
  scrollRegion.addEventListener("scroll", maybeLoadNextPage);

  renderWindow();
  void loadPreviousPages().then(maybeLoadNextPage);
})();
