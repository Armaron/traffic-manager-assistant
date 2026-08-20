export const AUTO_TRANSLATE_STORAGE_KEY = "traffic-manager-auto-translate";

export function readAutoTranslatePreference(): boolean {
  try {
    const stored = localStorage.getItem(AUTO_TRANSLATE_STORAGE_KEY);
    if (stored === "off") {
      return false;
    }
    if (stored === "on") {
      return true;
    }
  } catch {
    // Private mode still defaults to on.
  }
  return true;
}

export function writeAutoTranslatePreference(enabled: boolean): void {
  try {
    localStorage.setItem(AUTO_TRANSLATE_STORAGE_KEY, enabled ? "on" : "off");
  } catch {
    // Preference still applies for this session.
  }
}
