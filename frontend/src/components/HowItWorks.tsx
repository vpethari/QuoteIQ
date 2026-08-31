export function HowItWorks() {
  return (
    <section id="how-it-works" className="how" aria-label="How QuoteIQ works">
      <ol className="how-steps">
        <li>
          <span className="how-n">01</span>
          <h3>Upload</h3>
          <p>Drop in your Excel or PDF quote.</p>
        </li>
        <li>
          <span className="how-n">02</span>
          <h3>Understand</h3>
          <p>QuoteIQ extracts and normalizes line items.</p>
        </li>
        <li>
          <span className="how-n">03</span>
          <h3>Match</h3>
          <p>Products are compared against the Atkore catalog.</p>
        </li>
        <li>
          <span className="how-n">04</span>
          <h3>Export</h3>
          <p>Download a clean CPQ-ready CSV.</p>
        </li>
      </ol>
    </section>
  );
}
