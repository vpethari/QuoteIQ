interface Props {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}

export function CustomerSelect({ value, disabled, onChange }: Props) {
  return (
    <div className="customer-select">
      <div className="option-copy">
        <p className="option-title">Customer (optional)</p>
        <p id="customer-select-help">
          Ranks matches by this customer&apos;s own purchase history when available. Enter any part
          of a customer name, or a Bill-To / Ship-To account number.
        </p>
      </div>
      <input
        type="text"
        className="customer-select-input"
        value={value}
        disabled={disabled}
        placeholder="Customer name, Bill-To #, or Ship-To #..."
        aria-describedby="customer-select-help"
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
