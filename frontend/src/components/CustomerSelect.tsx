interface Props {
  value: string;
  customers: string[];
  disabled?: boolean;
  onChange: (value: string) => void;
}

// A plain <input list> + <datalist> gives native type-ahead filtering over
// the (potentially large) customer list with no extra dependency -- a
// dropdown with 200+ options would be unusable without one.
export function CustomerSelect({ value, customers, disabled, onChange }: Props) {
  return (
    <div className="customer-select">
      <div className="option-copy">
        <p className="option-title">Customer (optional)</p>
        <p id="customer-select-help">
          Ranks matches by this customer&apos;s own purchase history when available.
        </p>
      </div>
      <input
        type="text"
        className="customer-select-input"
        list="customer-select-options"
        value={value}
        disabled={disabled}
        placeholder="Start typing a customer name..."
        aria-describedby="customer-select-help"
        onChange={(event) => onChange(event.target.value)}
      />
      <datalist id="customer-select-options">
        {customers.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
    </div>
  );
}
