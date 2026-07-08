import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function LogSheet() {
  const [rows, setRows] = useState([]);
  const load = async () => {
    const res = await api.get("/logs");
    setRows(res.data);
  };
  useEffect(() => { load(); }, []);
  return (
    <div className="cfg-sheet">
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <h2>Macro_Log</h2>
        <button className="xl-btn" onClick={load} data-testid="log-refresh">Refresh</button>
      </div>
      <div className="note">Timestamped action log written by Moniteur.</div>
      <table className="xl-grid" data-testid="log-table">
        <thead><tr><th style={{ minWidth: 190 }}>Timestamp (UTC)</th><th style={{ minWidth: 500 }}>Action</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ fontFamily: "monospace", fontSize: 11 }}>{r.ts?.replace("T", " ").slice(0, 19)}</td>
              <td>{r.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
