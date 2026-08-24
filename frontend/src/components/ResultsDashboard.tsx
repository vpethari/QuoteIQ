import type { QuoteSummary } from "../types/quote";
import { IconDownload } from "./Icons";
import { SummaryCards } from "./SummaryCards";

interface Props {
  summary: QuoteSummary | null;
  onDownload: () => void;
  loading: boolean;
  canDownload: boolean;
}

export function ResultsDashboard({ summary, onDownload, loading, canDownload }: Props) {
  return (
    <section className="results-dash" aria-labelledby="results-heading">
      <div className="results-head">
        <div>
          <h2 id="results-heading">Quote Summary</h2>
        </div>
        <button
          type="button"
          className="btn-csv"
          disabled={loading || !canDownload}
          onClick={onDownload}
          title="Download QuoteIQ_results.csv"
        >
          <IconDownload size={16} />
          Download CSV
        </button>
      </div>
      <SummaryCards summary={summary} />
    </section>
  );
}
