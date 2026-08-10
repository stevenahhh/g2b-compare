import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import App from "../src/App.svelte";

describe("desktop shell", () => {
  it("renders the Korean application identity", () => {
    render(App);

    expect(
      screen.getByRole("heading", { name: "나라장터 물품 비교" }),
    ).toBeInTheDocument();
    expect(screen.getByText("로컬 데스크톱 앱 준비 중")).toBeInTheDocument();
  });
});
