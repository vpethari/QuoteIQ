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
import { ApiError, downloadBlob, processQuote, processQuoteCsv } from "./services/api";
import type { QuoteProcessResponse } from "./types/quote";

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [useAI, setUseAI] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<QuoteProcessResponse | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

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
