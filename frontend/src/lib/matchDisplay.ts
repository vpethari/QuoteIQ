import type { MatchStatus, QuoteMatchResult, QuoteSummary } from "../types/quote";

export type StatusBadge = "MATCHED" | "REVIEW_REQUIRED" | "NO_MATCH";

export function statusBadge(status: MatchStatus): StatusBadge {
  if (status === "REVIEW_REQUIRED") {
    return "REVIEW_REQUIRED";
  }
  if (status === "NO_MATCH") {
    return "NO_MATCH";
  }
  return "MATCHED";
}

export function statusLabel(status: MatchStatus): string {
  const badge = statusBadge(status);
  if (badge === "REVIEW_REQUIRED") {
    return "REVIEW REQUIRED";
  }
  if (badge === "NO_MATCH") {
    return "NO MATCH";
  }
  return "MATCHED";
}

export function officialPartNumber(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return value;
}

export function formatOptionalPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "N/A";
  }
  return `${Math.round(value)}%`;
}

export function percentTone(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (value >= 90) {
    return "score-high";
  }
  if (value >= 58) {
    return "score-mid";
  }
  return "score-low";
}

export function overallPercent(row: QuoteMatchResult): string {
  if (row.match_status === "NO_MATCH") {
    const value = row.overall_match_score ?? row.matching_percentage;
    if (value === null || value === undefined) {
      return "0%";
    }
    return `${Math.round(value)}%`;
  }
  const value = row.overall_match_score ?? row.matching_percentage;
  if (value === null || value === undefined) {
    return "N/A";
  }
  return `${Math.round(value)}%`;
}

export function formatQuantity(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return String(value);
}

export function matchRate(summary: QuoteSummary): string {
  if (!summary.total) {
    return "0%";
  }
  return `${Math.round((summary.matched / summary.total) * 100)}%`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
