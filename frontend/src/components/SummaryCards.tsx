import { IconChart, IconCheck, IconDoc, IconWarn, IconX } from "./Icons";
import { matchRate } from "../lib/matchDisplay";
import type { QuoteSummary } from "../types/quote";

const ICONS = {
  "Total Lines": IconDoc,
  Matched: IconCheck,
  "Review Required": IconWarn,
  "No Match": IconX,
  "Match Rate": IconChart,
} as const;

export function SummaryCards({
  summary,
}: {
  summary: QuoteSummary | null;
}) {
  const cards = [
    { label: "Total Lines", value: summary ? String(summary.total) : "—", tone: "green" },
    { label: "Matched", value: summary ? String(summary.matched) : "—", tone: "green" },
    { label: "Review Required", value: summary ? String(summary.review_required) : "—", tone: "orange" },
    { label: "No Match", value: summary ? String(summary.no_match) : "—", tone: "red" },
    { label: "Match Rate", value: summary ? matchRate(summary) : "—", tone: "navy" },
  ] as const;

  return (
    <dl className="summary">
      {cards.map((card) => {
        const Icon = ICONS[card.label];
        return (
          <div key={card.label} className={`summary-tile tone-${card.tone}`}>
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
