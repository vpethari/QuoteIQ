function SampleFormatTable() {
  return (
    <table className="workflow-sample-table">
      <thead>
        <tr>
          <th>Description</th>
          <th>Qty</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Cable Cleats</td>
          <td>120</td>
        </tr>
      </tbody>
    </table>
  );
}

export function WorkflowGraphic() {
  return (
    <div className="workflow" aria-hidden="true">
      <div className="workflow-inputs">
        <div className="workflow-card xlsx">
          <span className="xlsx-icon" />
          <span className="workflow-kicker">XLSX</span>
          <strong>quote.xlsx</strong>
          <span className="workflow-sample">Sample format</span>
          <SampleFormatTable />
        </div>
        <div className="workflow-card pdf">
          <span className="pdf-icon" />
          <span className="workflow-kicker">PDF</span>
          <strong>quote.pdf</strong>
          <span className="workflow-sample">Sample format</span>
          <SampleFormatTable />
        </div>
      </div>
      <div className="workflow-connector">
        <span />
      </div>
      <div className="workflow-node">
        i<span>Q</span>
      </div>
      <div className="workflow-connector">
        <span />
      </div>
      <div className="workflow-card out">
        <span className="workflow-kicker">CPQ READY</span>
        <strong>CSV</strong>
        <span className="workflow-check">
          <svg viewBox="0 0 16 16" width="14" height="14">
            <circle cx="8" cy="8" r="7" fill="#43A13F" />
            <path d="M4.5 8.2 L7 10.6 L11.5 5.6" fill="none" stroke="#fff" strokeWidth="1.6" />
          </svg>
          Salesforce CPQ
        </span>
      </div>
    </div>
  );
}
