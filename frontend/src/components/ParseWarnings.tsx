import { IconWarn } from "./Icons";

interface Props {
  warnings: string[];
  onDismiss: () => void;
}

export function ParseWarnings({ warnings, onDismiss }: Props) {
  if (warnings.length === 0) {
    return null;
  }

  return (
    <div className="parse-warnings" role="status">
      <span className="parse-warnings-icon">
        <IconWarn size={18} />
      </span>
      <ul>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
      <button type="button" className="parse-warnings-dismiss" onClick={onDismiss} aria-label="Dismiss">
        &times;
      </button>
    </div>
  );
}
