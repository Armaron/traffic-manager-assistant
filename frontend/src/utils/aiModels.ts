import type { AIModelInfo } from "../types/digest";

export const REVIEW_MODEL_STORAGE_KEY = "traffic-manager-digest-review-model";
export const QA_MODEL_STORAGE_KEY = "traffic-manager-digest-qa-model";
export const QA_SESSION_STORAGE_KEY = "traffic-manager-digest-qa-session";

export function costMarks(level: number): string {
  const n = Math.min(3, Math.max(1, Math.round(level) || 1));
  return "$".repeat(n);
}

export function modelLabel(models: AIModelInfo[], id: string | null | undefined): string {
  return models.find((item) => item.id === id)?.label || id || "";
}

export function resolveStoredModel(
  storageKey: string,
  models: AIModelInfo[],
  fallback: string,
  storage: Pick<Storage, "getItem" | "removeItem"> = window.localStorage,
): string {
  const allowed = new Set(models.map((item) => item.id));
  const fallbackId = allowed.has(fallback) ? fallback : models[0]?.id || "";
  try {
    const stored = storage.getItem(storageKey);
    if (stored && allowed.has(stored)) {
      return stored;
    }
    if (stored) {
      storage.removeItem(storageKey);
    }
  } catch {
    // Private mode may block storage.
  }
  return fallbackId;
}

export function writeStoredModel(storageKey: string, modelId: string): void {
  try {
    window.localStorage.setItem(storageKey, modelId);
  } catch {
    // Ignore quota / private mode.
  }
}
