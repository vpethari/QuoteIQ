import { FeatureCallouts } from "./FeatureCallouts";
import { IconPlay, IconUpload } from "./Icons";
import { WorkflowGraphic } from "./WorkflowGraphic";

interface Props {
  onUpload: () => void;
  onHowItWorks: () => void;
}

export function Hero({ onUpload, onHowItWorks }: Props) {
  return (
    <section className="hero" aria-labelledby="hero-heading">
      <div className="hero-copy">
        <h1 id="hero-heading">QuoteIQ</h1>
        <p className="hero-headline">Transform messy RFQs into clean, CPQ-ready quotes.</p>
        <p className="hero-lead">
          Upload your Excel documents. Our AI-powered matching engine identifies Atkore products,
          validates part numbers, and delivers a clean CSV ready for Salesforce CPQ.
        </p>
        <div className="hero-actions">
          <button type="button" className="btn-orange" onClick={onUpload}>
            <IconUpload />
            Upload a Document
          </button>
          <button type="button" className="btn-outline" onClick={onHowItWorks}>
            <IconPlay />
            See How It Works
          </button>
        </div>
      </div>
      <div className="hero-visual">
        <WorkflowGraphic />
        <FeatureCallouts />
      </div>
    </section>
  );
}
