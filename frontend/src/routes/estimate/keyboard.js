export function titleKeyAction(key) {
  if (key === "Enter") return "commit";
  if (key === "Escape") return "cancel";
  return null;
}
export const closeOnEscape = (key) => key === "Escape";
