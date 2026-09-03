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
    return "REVIEW_REQUIRED";
  }
  if (badge === "NO_MATCH") {
    return "NO_MATCH";
  }
  return "MATCH";
}

export function formatProductcode(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  const text = String(value);
  if (/^\d{1,3}(,\d{3})+$/.test(text)) {
    return text.replace(/,/g, "");
  }
  return text;
}

export function displayedProductcode(row: QuoteMatchResult): string {
  if (statusBadge(row.match_status) !== "MATCHED") {
    return "No part selected";
  }
  const code = formatProductcode(
    row.match_evidence?.matched_part_number || row.matched_part_number,
  );
  if (!code) {
    return "No part selected";
  }
  return code;
}

function matchedCandidate(row: QuoteMatchResult) {
  if (statusBadge(row.match_status) !== "MATCHED") {
    return null;
  }
  const code = formatProductcode(row.match_evidence?.matched_part_number || row.matched_part_number);
  if (!code) {
    return null;
  }
  return row.candidates?.find((item) => formatProductcode(item.official_part_number) === code) ?? null;
}

// productmaster.Productcode is an internal-only key; productmaster.name is
// what external agents actually use to quote and order, so that's what
// "Matched Part Number" displays as -- Productcode is still what drives
// matching/selection under the hood (see onSelectCandidate), just not shown.
export function displayedMatchedName(row: QuoteMatchResult): string {
  const candidate = matchedCandidate(row);
  if (!candidate) {
    return displayedProductcode(row);
  }
  return candidate.name || candidate.description || displayedProductcode(row);
}

const ATKORE_PRODUCTS_URL = "https://www.atkore.com/product/";

// productmaster.name is raw, unnormalized catalog data -- some rows carry
// fixed-width padding (e.g. "P6291     EG") that would otherwise turn into a
// broken-looking link full of encoded spaces ("P6291%20%20%20%20%20EG").
// Strip the surrounding whitespace and join the remaining words with "-"
// for a clean slug. This only affects the link; the name is still displayed
// as-is elsewhere.
function trimmedNameForLink(name: string): string {
  return name.trim().replace(/\s+/g, "-");
}

export function atkoreUrlForName(name: string | null | undefined): string | null {
  if (!name) {
    return null;
  }
  const trimmed = trimmedNameForLink(name);
  if (!trimmed) {
    return null;
  }
  return `${ATKORE_PRODUCTS_URL}${encodeURIComponent(trimmed)}`;
}

export function atkoreProductUrl(row: QuoteMatchResult): string | null {
  return atkoreUrlForName(matchedCandidate(row)?.name);
}

export function candidateProductcode(candidate: {
  productcode?: string | null;
  official_part_number?: string | null;
  salsify_id?: string | null;
}): string {
  return formatProductcode(candidate.productcode || candidate.official_part_number) || "—";
}

export function matchWhyHeadline(row: QuoteMatchResult): string {
  if (row.selection_type === "USER_SELECTED" || row.match_type === "USER_SELECTED") {
    return "User Selected Match";
  }
  if (row.match_evidence?.headline) {
    return row.match_evidence.headline;
  }
  const badge = statusBadge(row.match_status);
  if (badge === "REVIEW_REQUIRED") {
    return "Multiple products have equivalent description matches";
  }
  if (badge === "NO_MATCH") {
    return "No sufficiently similar product found";
  }
  if (row.part_number_match && row.description_match) {
    return "Exact Productcode + Description Match";
  }
  if (row.part_number_match) {
    return "Exact Productcode Match";
  }
  if (row.description_match) {
    return "Description Match";
  }
  return row.match_reason || "Catalog match";
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
  if (value >= 25) {
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
