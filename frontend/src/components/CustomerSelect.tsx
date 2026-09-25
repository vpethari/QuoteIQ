interface Props {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}

export function CustomerSelect({ value, disabled, onChange }: Props) {
  return (
    <div className="customer-select">
      <div className="option-copy">
        <p className="option-title">Customer *</p>
        <p id="customer-select-help">
          Required. Ranks matches by this customer&apos;s own purchase history when available.
          Enter a Ship-To / Bill-To account number, or any part of a customer name.
        </p>
      </div>
      <input
        type="text"
        className="customer-select-input"
        value={value}
        disabled={disabled}
        required
        placeholder="Ship-To #, Bill-To #, or customer name..."
        aria-describedby="customer-select-help"
        aria-required="true"
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
