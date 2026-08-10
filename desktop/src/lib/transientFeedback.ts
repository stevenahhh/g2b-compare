export const LEGACY_INTERACTION_INTERVAL_MS = 1_600;

export interface TransientFeedbackDeadline {
  cancel: () => void;
  reset: () => void;
}

export function createTransientFeedbackDeadline(
  clearFeedback: () => void,
): TransientFeedbackDeadline {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let version = 0;

  function cancel() {
    version += 1;
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  function reset() {
    cancel();
    const scheduledVersion = version;
    timer = setTimeout(() => {
      if (scheduledVersion !== version) return;
      timer = undefined;
      clearFeedback();
    }, LEGACY_INTERACTION_INTERVAL_MS);
  }

  return { cancel, reset };
}
