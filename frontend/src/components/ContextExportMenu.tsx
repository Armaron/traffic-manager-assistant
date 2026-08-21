const EXPORT_WARNING =
  "Файл содержит текст выбранных рабочих переписок. Передавайте его только туда, куда вы намерены отправить эти данные.";

type ContextExportMenuProps = {
  label?: string;
  disabled?: boolean;
  onDownload: (format: "md" | "json") => void;
};

export function ContextExportMenu({
  label = "Скачать контекст",
  disabled = false,
  onDownload,
}: ContextExportMenuProps) {
  return (
    <div className="export-menu">
      <details className="export-menu__details">
        <summary className="ghost-button" aria-disabled={disabled}>
          {label}
        </summary>
        <div className="export-menu__list">
          <button type="button" disabled={disabled} onClick={() => onDownload("md")}>
            Для ChatGPT (.md)
          </button>
          <button type="button" disabled={disabled} onClick={() => onDownload("json")}>
            AI Context (.json)
          </button>
        </div>
      </details>
      <p className="export-menu__hint" title={EXPORT_WARNING}>
        {EXPORT_WARNING}
      </p>
    </div>
  );
}

export { EXPORT_WARNING };
