interface Props {
  message: string;
}

export function ErrorCard({ message }: Props) {
  const unavailable = message.toLowerCase().includes("unavailable");
  return (
    <div className="error-card" role="alert">
      <h2>{unavailable ? "QuoteIQ service unavailable" : "Unable to process quote"}</h2>
      <p>
        {unavailable
          ? "Confirm the backend is running and try again."
          : message || "Please make sure the QuoteIQ service is running and try again."}
      </p>
    </div>
  );
}
