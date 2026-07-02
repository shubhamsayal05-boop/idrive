import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

const TEAL = "#17375E";
const MS = ["M1", "M2", "M3", "M4"];

function pct(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return (n * 100).toFixed(2) + "%";
}
function num(v, d = 2) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toFixed(d);
}

function SeuilTable({ seuils }) {
  if (!seuils) return null;
  return (
    <table className="xl-grid" style={{ marginTop: 4, fontSize: 11.5 }}>
      <thead>
        <tr><th>Threshold</th>{MS.map((m) => <th key={m}>{m}</th>)}</tr>
      </thead>
      <tbody>
        <tr><td className="rowhead" style={{ background: "#C6EFCE" }}>Green / Orange</td>
          {(seuils.vert_orange || []).map((v, i) => <td key={i}>{num(v, 2)}</td>)}</tr>
        <tr><td className="rowhead" style={{ background: "#FFEB9C" }}>Orange / Red</td>
          {(seuils.orange_rouge || []).map((v, i) => <td key={i}>{num(v, 2)}</td>)}</tr>
        <tr><td className="rowhead">Full scale</td>
          {(seuils.pleine_echelle || []).map((v, i) => <td key={i}>{num(v, 2)}</td>)}</tr>
      </tbody>
    </table>
  );
}

function Axis({ title, axis, isTaux }) {
  if (!axis) return null;
  return (
    <div style={{ border: "1px solid #ccc", padding: "8px 10px", marginBottom: 12, minWidth: 360 }}>
      <div style={{ fontWeight: 700, color: TEAL, marginBottom: 4 }}>{title}</div>
      {axis.vehicles ? (
        <table className="xl-grid" style={{ fontSize: 11.5, marginBottom: 6 }}>
          <thead><tr><th>Vehicle</th><th>X</th><th>Y</th></tr></thead>
          <tbody>
            {axis.vehicles.filter((v) => v.name || v.x !== null).map((v, i) => (
              <tr key={i}><td>{v.name || "(marker)"}</td>
                <td>{isTaux ? pct(v.x) : num(v.x, 4)}</td><td>{num(v.y, 1)}</td></tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {axis.x !== undefined ? (
        <div style={{ fontSize: 12, marginBottom: 4 }}>
          Plotted value (X marker): <b>{isTaux ? pct(axis.x) : num(axis.x, 4)}</b>
        </div>
      ) : null}
      <table className="xl-grid" style={{ fontSize: 11.5 }}>
        <tbody>
          <tr><td className="rowhead" style={{ background: "#FBC7C7" }}>Red index</td><td>{num(axis.index_rouge, 3)}</td>
            <td className="rowhead" style={{ background: "#FFEB9C" }}>Orange index</td><td>{num(axis.index_orange, 3)}</td></tr>
          <tr><td className="rowhead" style={{ background: "#C6EFCE" }}>Green index</td><td>{num(axis.index_vert, 3)}</td>
            <td className="rowhead">Full scale</td><td>{num(axis.pleine_echelle, 3)}</td></tr>
        </tbody>
      </table>
      <SeuilTable seuils={axis.seuils_par_milestone} />
    </div>
  );
}

export default function GraphStatusSheet() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.get("/config/graph_status")
      .then((r) => setData(r.data))
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div style={{ padding: 20, color: "#a00" }}>Failed to load Graph_status: {err}</div>;
  if (!data) return <div style={{ padding: 20, color: "#666" }}>Loading Graph_status…</div>;

  return (
    <div style={{ padding: "10px 16px 50px", minWidth: 1000 }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: TEAL }}>Graph_status</div>
      <div style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>
        Verdict thresholds driving the global Low / Medium / High Risk classification.
        Index axis uses x = (index/100)<sup>GLOBALPUISS=5</sup>; the verdict is the 3×3
        combination of the taux colour and the index colour at the project milestone.
      </div>

      <div style={{ fontWeight: 700, color: TEAL, fontSize: 14, margin: "6px 0" }}>DRIVABILITY</div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <Axis title="Drivability — Index axis" axis={data.drivability?.index} isTaux={false} />
        <Axis title="Drivability — Taux (weighted-%) axis" axis={data.drivability?.taux} isTaux={true} />
      </div>

      <div style={{ fontWeight: 700, color: TEAL, fontSize: 14, margin: "12px 0 6px" }}>RESPONSIVENESS</div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <Axis title="Responsiveness — Index axis" axis={data.responsiveness?.index} isTaux={false} />
        <Axis title="Responsiveness — Taux (weighted-%) axis" axis={data.responsiveness?.taux} isTaux={true} />
      </div>

      <div style={{ marginTop: 16, fontSize: 12, color: "#444", maxWidth: 720 }}>
        <b>Verdict matrix</b> (taux row × index column):
        <table className="xl-grid" style={{ marginTop: 4, fontSize: 11.5 }}>
          <thead><tr><th></th><th>index green</th><th>index yellow</th><th>index red</th></tr></thead>
          <tbody>
            <tr><td className="rowhead" style={{ background: "#C6EFCE" }}>taux green</td>
              <td style={{ background: "#C6EFCE" }}>Low</td><td style={{ background: "#C6EFCE" }}>Low</td><td style={{ background: "#FFEB9C" }}>Medium</td></tr>
            <tr><td className="rowhead" style={{ background: "#FFEB9C" }}>taux yellow</td>
              <td style={{ background: "#FFEB9C" }}>Medium</td><td style={{ background: "#FFEB9C" }}>Medium</td><td style={{ background: "#FBC7C7" }}>High</td></tr>
            <tr><td className="rowhead" style={{ background: "#FBC7C7" }}>taux red</td>
              <td style={{ background: "#FBC7C7" }}>High</td><td style={{ background: "#FBC7C7" }}>High</td><td style={{ background: "#FBC7C7" }}>High</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
