type AutoTranslateToggleProps = {
  enabled: boolean;
  backendEnabled: boolean;
  onChange: (enabled: boolean) => void;
};

export function AutoTranslateToggle({
  enabled,
  backendEnabled,
  onChange,
}: AutoTranslateToggleProps) {
  const effective = enabled && backendEnabled;
  return (
    <div className="theme-switcher auto-translate-toggle">
      <span className="theme-switcher__label">Auto-translate messages</span>
      <button
        type="button"
        className={`switch${effective ? " is-on" : ""}`}
        onClick={() => onChange(!enabled)}
        disabled={!backendEnabled}
        aria-pressed={effective}
        aria-label={effective ? "Turn auto-translate off" : "Turn auto-translate on"}
      >
        <span className="switch__track" aria-hidden="true">
          <span className="switch__knob" />
        </span>
        <span className="switch__label">{backendEnabled ? (enabled ? "On" : "Off") : "Off"}</span>
      </button>
    </div>
  );
}
