import { IconCheck, IconGear, IconPerson } from "./Icons";

export function FeatureCallouts() {
  return (
    <section className="capabilities" aria-label="QuoteIQ capabilities">
      <article className="capability">
        <IconGear />
        <h2>Multi-Layer Matching</h2>
        <p>PIM data and AI reasoning</p>
      </article>
      <article className="capability">
        <IconCheck size={22} />
        <h2>Confidence Scoring</h2>
        <p>Every match scored 0%–100%</p>
      </article>
      <article className="capability">
        <IconPerson />
        <h2>Human-in-the-Loop</h2>
        <p>Review and verify low confidence items</p>
      </article>
    </section>
  );
}
