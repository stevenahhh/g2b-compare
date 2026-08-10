import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConfirmModal from "./ConfirmModal.svelte";

afterEach(() => cleanup());

describe("confirm modal keyboard flow", () => {
  it("moves focus into the dialog, traps Tab, and restores the opener", async () => {
    const opener = document.createElement("button");
    opener.textContent = "문서 삭제 열기";
    document.body.append(opener);
    opener.focus();

    const view = render(ConfirmModal, {
      props: {
        title: "문서 삭제",
        message: "이 문서를 영구적으로 삭제할까요?",
        confirmLabel: "삭제",
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    await Promise.resolve();
    await tick();

    const cancel = screen.getByRole("button", { name: "취소" });
    const confirm = screen.getByRole("button", { name: "삭제" });
    expect(cancel).toHaveFocus();

    confirm.focus();
    await fireEvent.keyDown(window, { key: "Tab" });
    expect(cancel).toHaveFocus();

    await fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();

    view.unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("closes on Escape", async () => {
    const onCancel = vi.fn();
    render(ConfirmModal, {
      props: {
        title: "문서 삭제",
        message: "이 문서를 영구적으로 삭제할까요?",
        onConfirm: vi.fn(),
        onCancel,
      },
    });

    await fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
