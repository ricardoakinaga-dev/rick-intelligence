// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConfirmDialog } from "../../components/ui";

let root: Root;
let container: HTMLDivElement;
let trigger: HTMLButtonElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  trigger = document.createElement("button"); trigger.textContent = "Open"; document.body.append(trigger); trigger.focus();
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); document.body.replaceChildren(); });
async function render(busy: boolean, open = true, onCancel = vi.fn()) {
  await act(async () => { root.render(<ConfirmDialog open={open} busy={busy} title="Excluir" description="Confirmar exclusão" onCancel={onCancel} onConfirm={() => {}} />); });
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)); });
  return onCancel;
}
function key(value: string, shiftKey = false) {
  const event = new KeyboardEvent("keydown", { key: value, shiftKey, bubbles: true, cancelable: true });
  document.activeElement?.dispatchEvent(event); return event;
}
it("keeps forward and backward focus in a busy modal and restores the trigger", async () => {
  const cancel = await render(false);
  expect(document.activeElement?.textContent).toBe("Cancelar");
  await render(true, true, cancel);
  expect(key("Tab").defaultPrevented).toBe(true);
  expect(document.activeElement?.getAttribute("role")).toBe("dialog");
  expect(key("Tab", true).defaultPrevented).toBe(true);
  expect(document.activeElement?.closest('[role="dialog"]')).not.toBeNull();
  expect(container.querySelector('[role="dialog"]')?.getAttribute("aria-busy")).toBe("true");
  key("Escape"); expect(cancel).not.toHaveBeenCalled();
  await render(false, false); expect(document.activeElement).toBe(trigger);
});
it("opens busy with a focusable fallback, then returns to enabled controls", async () => {
  await render(true); expect(document.activeElement?.getAttribute("role")).toBe("dialog");
  await render(false); key("Tab"); expect(document.activeElement?.textContent).toBe("Cancelar");
});
it("wraps enabled controls and permits Escape", async () => {
  const cancel = await render(false);
  key("Tab", true); expect(document.activeElement?.textContent).toBe("Confirmar");
  key("Tab"); expect(document.activeElement?.textContent).toBe("Cancelar");
  key("Escape"); expect(cancel).toHaveBeenCalledOnce();
});
