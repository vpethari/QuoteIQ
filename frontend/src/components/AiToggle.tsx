interface Props {
  enabled: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}

export function AiToggle({ enabled, disabled, onChange }: Props) {
  return (
    <div className="ai-toggle">
      <label className="switch">
        <input
          type="checkbox"
          checked={enabled}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          aria-describedby="ai-help"
        />
        <span className="slider" />
      </label>
      <div className="option-copy">
        <p className="option-title">Use AI matching</p>
        <p id="ai-help">
          Optional. AI only reviews catalog candidates already found. It does not invent part numbers.
        </p>
      </div>
    </div>
  );
}
