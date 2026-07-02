import { useWorkbook } from "@/components/Workbook";

const CHANGELOG = [
  ["v29.2.1", "Web application: FastAPI scoring engine with a React workbook-style UI. Import pipeline (TRIE), SDV event classifier (64 rules), agreement-index scoring, priority grids, criticality, status dots, global verdicts, and PPTX/PDF reporting."],
  ["v29.2.0", "Automatic Transmission variant; per-SDV milestone blocks in SETTINGS."],
  ["v29.1.x", "Drivability and Responsiveness tracks; per-SDV summary panel and coverage."],
  ["…", "Earlier releases — see the full changelog history."],
];

export default function VersionsSheet() {
  const { openTab } = useWorkbook();
  return (
    <div className="cfg-sheet">
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <h2>VERSIONS — tool changelog</h2>
        <button className="xl-btn" onClick={() => openTab("HOME")} data-testid="versions-exit">Exit</button>
      </div>
      <table className="xl-grid" style={{ marginTop: 8 }}>
        <thead><tr><th style={{ minWidth: 160 }}>Version</th><th style={{ minWidth: 620 }}>Changes</th></tr></thead>
        <tbody>
          {CHANGELOG.map(([v, c]) => (
            <tr key={v}><td style={{ fontWeight: 700 }}>{v}</td><td style={{ whiteSpace: "normal" }}>{c}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
