import { useMemo, useState } from "react";
import { BackToTop } from "./components/BackToTop";
import { ErrorCard } from "./components/ErrorCard";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { Hero } from "./components/Hero";
import { HowItWorks } from "./components/HowItWorks";
import { ParseWarnings } from "./components/ParseWarnings";
import { ProcessingState } from "./components/ProcessingState";
import { ResultsDashboard } from "./components/ResultsDashboard";
import { ResultsTable } from "./components/ResultsTable";
import type { SummaryFilter } from "./components/SummaryCards";
import { UploadDropzone } from "./components/UploadDropzone";
import { UploadPanel } from "./components/UploadPanel";
import { statusBadge } from "./lib/matchDisplay";
import {
  ApiError,
  downloadBlob,
  downloadCpqReadyCsv,
  downloadResultsCsv,
  processQuote,
  selectQuoteMatch,
} from "./services/api";
import type { QuoteMatchResult, QuoteProcessResponse } from "./types/quote";

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function summarize(results: QuoteMatchResult[]): QuoteProcessResponse["summary"] {
  let matched = 0;
  let review = 0;
  let noMatch = 0;
  for (const row of results) {
    if (row.match_status === "REVIEW_REQUIRED") {
      review += 1;
    } else if (row.match_status === "NO_MATCH") {
      noMatch += 1;
    } else {
      matched += 1;
    }
  }
  return { total: results.length, matched, review_required: review, no_match: noMatch };
}

export default function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [useAI, setUseAI] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<QuoteProcessResponse | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const [selectingIndex, setSelectingIndex] = useState<number | null>(null);
  const [activeFilter, setActiveFilter] = useState<SummaryFilter>("ALL");
  const [warningsDismissed, setWarningsDismissed] = useState(false);

  const visibleIndices = useMemo(() => {
    if (!results) {
      return [];
    }
    if (activeFilter === "ALL") {
      return results.results.map((_, index) => index);
    }
    return results.results
      .map((_, index) => index)
      .filter((index) => statusBadge(results.results[index].match_status) === activeFilter);
  }, [results, activeFilter]);

  function handleFile(file: File | null, message?: string) {
    setSelectedFile(file);
    setResults(null);
    setActiveFilter("ALL");
    setWarningsDismissed(false);
    setError(message ?? null);
  }

  async function onProcess() {
    if (!selectedFile || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = await processQuote(selectedFile, useAI);
      setResults(payload);
      setExpandedRows(new Set());
      setActiveFilter("ALL");
      setWarningsDismissed(false);
    } catch (err) {
      setResults(null);
      setError(
        err instanceof ApiError
          ? err.message
          : "Please make sure the QuoteIQ service is running and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function onDownload() {
    if (!results || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const blob = await downloadResultsCsv(results.results);
      downloadBlob(blob, "QuoteIQ_results.csv");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Please make sure the QuoteIQ service is running and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function onDownloadCpq() {
    if (!results || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const blob = await downloadCpqReadyCsv(results.results);
      downloadBlob(blob, "QuoteIQ_CPQ_Ready.csv");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Please make sure the QuoteIQ service is running and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function onSelectCandidate(index: number, row: QuoteMatchResult, productcode: string) {
    if (selectingIndex !== null) {
      return;
    }
    setSelectingIndex(index);
    setError(null);
    try {
      const updated = await selectQuoteMatch({
        quote_line_id: row.quote_line_id || `${row.source_row ?? index}|${row.requested_description}`,
        productcode,
        result: row,
      });
      setResults((current) => {
        if (!current) {
          return current;
        }
        const nextResults = current.results.map((item, itemIndex) => (itemIndex === index ? updated : item));
        return { summary: summarize(nextResults), results: nextResults };
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Unable to save the selected product. Please try again.",
      );
    } finally {
      setSelectingIndex(null);
    }
  }

  return (
    <div className="app" id="top">
      <Header onGetStarted={() => scrollToId("upload")} />
      <main>
        <div className="hero-wrap">
          <Hero onUpload={() => scrollToId("upload")} onHowItWorks={() => scrollToId("how-it-works")} />
        </div>
        <HowItWorks />
        <Footer />

        <div className="dashboard">
          <div className="workspace-card">
            <div className="workspace-grid">
              <UploadDropzone loading={loading} onFile={handleFile} />
              <UploadPanel
                file={selectedFile}
                lineCount={results?.summary.total ?? null}
                loading={loading}
                useAI={useAI}
                onUseAI={setUseAI}
                onProcess={() => void onProcess()}
                onFile={handleFile}
              />
            </div>

            {!warningsDismissed && results?.parse_warnings?.length ? (
              <ParseWarnings warnings={results.parse_warnings} onDismiss={() => setWarningsDismissed(true)} />
            ) : null}

            <ResultsDashboard
              summary={results?.summary ?? null}
              onDownload={() => void onDownload()}
              onDownloadCpq={() => void onDownloadCpq()}
              loading={loading}
              canDownload={Boolean(results)}
              activeFilter={activeFilter}
              onFilterChange={setActiveFilter}
              visibleCount={visibleIndices.length}
            />

            {loading ? <ProcessingState /> : null}
            {error ? <ErrorCard message={error} /> : null}

            {results ? (
              <ResultsTable
                results={results.results}
                visibleIndices={visibleIndices}
                expandedRows={expandedRows}
                selectingIndex={selectingIndex}
                onSelectCandidate={(index, row, productcode) => {
                  void onSelectCandidate(index, row, productcode);
                }}
                onToggle={(index) => {
                  setExpandedRows((current) => {
                    const next = new Set(current);
                    if (next.has(index)) {
                      next.delete(index);
                    } else {
                      next.add(index);
                    }
                    return next;
                  });
                }}
              />
            ) : null}
          </div>
        </div>
      </main>
      <BackToTop />
    </div>
  );
}
