import { useState } from "react";

import { type ThemeChoice, readThemeChoice, setThemeChoice } from "../theme";

const OPTIONS: { id: ThemeChoice; label: string }[] = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "system", label: "System" },
];

export function ThemeSwitcher() {
  const [choice, setChoice] = useState<ThemeChoice>(() => readThemeChoice());

  function select(next: ThemeChoice) {
    setChoice(next);
    setThemeChoice(next);
  }

  return (
    <div className="theme-switcher">
      <span className="theme-switcher__label">Theme</span>
      <div className="theme-switcher__options" role="radiogroup" aria-label="Theme">
        {OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={choice === option.id}
            className={choice === option.id ? "is-active" : ""}
            onClick={() => select(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
