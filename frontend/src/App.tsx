import { useState } from "react";
import { ErrorCard } from "./components/ErrorCard";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { Hero } from "./components/Hero";
import { HowItWorks } from "./components/HowItWorks";
import { ProcessingState } from "./components/ProcessingState";
import { ResultsDashboard } from "./components/ResultsDashboard";
import { ResultsTable } from "./components/ResultsTable";
import { UploadCard } from "./components/UploadCard";
import { ApiError, downloadBlob, processQuote, processQuoteCsv, selectQuoteMatch } from "./services/api";
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
    if (!selectedFile || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const blob = await processQuoteCsv(selectedFile, useAI);
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
              <UploadCard
                file={selectedFile}
                lineCount={results?.summary.total ?? null}
                loading={loading}
                useAI={useAI}
                onUseAI={setUseAI}
                onProcess={() => void onProcess()}
                onFile={(file, message) => {
                  setSelectedFile(file);
                  setResults(null);
                  setError(message ?? null);
                }}
              />
              <ResultsDashboard
                summary={results?.summary ?? null}
                onDownload={() => void onDownload()}
                loading={loading}
                canDownload={Boolean(selectedFile && results)}
              />
            </div>

            {loading ? <ProcessingState /> : null}
            {error ? <ErrorCard message={error} /> : null}

            {results ? (
              <ResultsTable
                results={results.results}
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
    </div>
  );
}
