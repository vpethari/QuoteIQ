import type { QuoteSummary } from "../types/quote";
import { IconDownload } from "./Icons";
import { SummaryCards, type SummaryFilter } from "./SummaryCards";

const FILTER_LABEL: Record<Exclude<SummaryFilter, "ALL">, string> = {
  MATCHED: "Matched",
  REVIEW_REQUIRED: "Review Required",
  NO_MATCH: "No Match",
};

interface Props {
  summary: QuoteSummary | null;
  onDownload: () => void;
  onDownloadCpq: () => void;
  loading: boolean;
  canDownload: boolean;
  activeFilter: SummaryFilter;
  onFilterChange: (filter: SummaryFilter) => void;
  visibleCount: number;
}

export function ResultsDashboard({
  summary,
  onDownload,
  onDownloadCpq,
  loading,
  canDownload,
  activeFilter,
  onFilterChange,
  visibleCount,
}: Props) {
  return (
    <section className="results-dash" aria-labelledby="results-heading">
      <div className="results-head">
        <div>
          <h2 id="results-heading">Quote Summary</h2>
        </div>
        <div className="results-head-actions">
          <button
            type="button"
            className="btn-csv"
            disabled={loading || !canDownload}
            onClick={onDownload}
            title="Download QuoteIQ_results.csv"
          >
            <IconDownload size={16} />
            Full Results
          </button>
          <button
            type="button"
            className="btn-csv"
            disabled={loading || !canDownload}
            onClick={onDownloadCpq}
            title="Download QuoteIQ_CPQ_Ready.csv (Part Number, Quantity for matched rows only)"
          >
            <IconDownload size={16} />
            CPQ Ready Items
          </button>
        </div>
      </div>
      <SummaryCards summary={summary} activeFilter={activeFilter} onFilterChange={onFilterChange} />
      {summary && activeFilter !== "ALL" ? (
        <div className="filter-bar">
          <span className="chip">
            Filtered: {FILTER_LABEL[activeFilter]} ({visibleCount})
            <button type="button" onClick={() => onFilterChange("ALL")} aria-label="Clear filter">
              &times;
            </button>
          </span>
        </div>
      ) : null}
    </section>
  );
}
