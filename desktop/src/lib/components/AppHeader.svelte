<script lang="ts">
  import brandLogo from "../../../../KakaoTalk_20260804_113126254.png";
  import {
    desktopUpdateClient,
    type UpdateClient,
  } from "../update";
  import UpdateControl from "./UpdateControl.svelte";

  type HeaderRoute = "catalog" | "estimates" | "data";

  let {
    active = "catalog",
    onNavigate = () => undefined,
    updateClient = desktopUpdateClient,
  }: {
    active?: HeaderRoute;
    onNavigate?: (route: HeaderRoute) => void;
    updateClient?: UpdateClient;
  } = $props();
</script>

<header class="app-header">
  <h1 class="visually-hidden">나라장터 물품 비교</h1>
  <button class="app-brand" type="button" aria-label="코리아넷 문서 작성 홈" onclick={() => onNavigate("estimates")}>
    <img src={brandLogo} alt="" />
  </button>
  <nav class="app-nav" aria-label="주요 메뉴">
    <button type="button" aria-current={active === "estimates" ? "page" : undefined} onclick={() => onNavigate("estimates")}>
      문서 작성
    </button>
    <button type="button" aria-current={active === "catalog" ? "page" : undefined} onclick={() => onNavigate("catalog")}>
      물품 검색
    </button>
    <button type="button" aria-current={active === "data" ? "page" : undefined} onclick={() => onNavigate("data")}>
      데이터 상태
    </button>
  </nav>
  <UpdateControl client={updateClient} />
</header>
