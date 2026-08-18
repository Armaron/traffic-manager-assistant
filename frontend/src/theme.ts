export const THEME_STORAGE_KEY = "traffic-manager-theme";

export type ThemeChoice = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

const LIGHT_BG = "#eef0f3";
const DARK_BG = "#0d1117";
const LIGHT_TEXT = "#1f2933";
const DARK_TEXT = "#e6edf3";

export function isThemeChoice(value: string | null): value is ThemeChoice {
  return value === "dark" || value === "light" || value === "system";
}

export function readThemeChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemeChoice(stored)) {
      return stored;
    }
  } catch {
    // Private mode / blocked storage still gets the dark default.
  }
  return "dark";
}

export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  if (choice === "light") {
    return "light";
  }
  if (choice === "dark") {
    return "dark";
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(choice: ThemeChoice): ResolvedTheme {
  const resolved = resolveTheme(choice);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.dataset.themeChoice = choice;
  root.style.colorScheme = resolved;
  root.style.backgroundColor = resolved === "light" ? LIGHT_BG : DARK_BG;
  root.style.color = resolved === "light" ? LIGHT_TEXT : DARK_TEXT;
  return resolved;
}

export function setThemeChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // Theme still applies for this session.
  }
  applyTheme(choice);
}

export function initTheme(): void {
  applyTheme(readThemeChoice());
  const media = window.matchMedia("(prefers-color-scheme: light)");
  const onChange = () => {
    if (readThemeChoice() === "system") {
      applyTheme("system");
    }
  };
  media.addEventListener("change", onChange);
}
