import type { KeyboardEvent } from "react";
import { IconChart, IconCheck, IconDoc, IconWarn, IconX } from "./Icons";
import { matchRate, type StatusBadge } from "../lib/matchDisplay";
import type { QuoteSummary } from "../types/quote";

export type SummaryFilter = StatusBadge | "ALL";

const ICONS = {
  "Total Lines": IconDoc,
  Matched: IconCheck,
  "Review Required": IconWarn,
  "No Match": IconX,
  "Match Rate": IconChart,
} as const;

interface Props {
  summary: QuoteSummary | null;
  activeFilter: SummaryFilter;
  onFilterChange: (filter: SummaryFilter) => void;
}

export function SummaryCards({ summary, activeFilter, onFilterChange }: Props) {
  const cards = [
    { label: "Total Lines", value: summary ? String(summary.total) : "—", tone: "green", filter: "ALL" },
    { label: "Matched", value: summary ? String(summary.matched) : "—", tone: "green", filter: "MATCHED" },
    {
      label: "Review Required",
      value: summary ? String(summary.review_required) : "—",
      tone: "orange",
      filter: "REVIEW_REQUIRED",
    },
    { label: "No Match", value: summary ? String(summary.no_match) : "—", tone: "red", filter: "NO_MATCH" },
    { label: "Match Rate", value: summary ? matchRate(summary) : "—", tone: "navy", filter: null },
  ] as const;

  return (
    <dl className="summary">
      {cards.map((card) => {
        const Icon = ICONS[card.label];
        const clickable = card.filter !== null && Boolean(summary);
        const isActive = card.filter !== null && activeFilter === card.filter;

        function toggle() {
          if (card.filter === null) {
            return;
          }
          onFilterChange(isActive ? "ALL" : card.filter);
        }

        function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
          }
        }

        return (
          <div
            key={card.label}
            className={[
              "summary-tile",
              `tone-${card.tone}`,
              clickable ? "is-clickable" : "",
              isActive ? "is-active" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            role={clickable ? "button" : undefined}
            tabIndex={clickable ? 0 : undefined}
            aria-pressed={clickable ? isActive : undefined}
            onClick={clickable ? toggle : undefined}
            onKeyDown={clickable ? onKeyDown : undefined}
          >
            <dt>
              <span className="summary-icon">
                <Icon />
              </span>
              {card.label}
            </dt>
            <dd>{card.value}</dd>
          </div>
        );
      })}
    </dl>
  );
}
