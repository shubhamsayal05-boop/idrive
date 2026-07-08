import { useEffect, useMemo, useState } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { api, fmt, getChannel, CELL_COLORS } from "@/lib/api";
import { useWorkbook } from "@/components/Workbook";

const TEAL = "#215967";
const HBLUE = "#538DD5";
const CRIT_FILL = { 1: "#FFC7CE", 2: "#FFEB9C", 3: "#C6EFCE" };

export default function SdvSheet({ name }) {
  const { openTab, refresh, setSelection } = useWorkbook();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [part, setPart] = useState("driv"); // driv | dyn
  const [colorFilter, setColorFilter] = useState(null); // null | RED | RY
  const [gearFilter, setGearFilter] = useState(null);
  const [showC3, setShowC3] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const res = await api.get(`/sdv/${encodeURIComponent(name)}`);
      setData(res.data);
    } catch (e) { setErr(e.response?.data?.detail || e.message); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [name]);

  const update = async () => {
    setBusy(true);
    try { await api.post("/rating/calculate"); await load(); await refresh(); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  const criteria = useMemo(() => {
    if (!data) return [];
    const key = part === "driv" ? "driv" : "resp";
    return (data.structure?.criteria || [])
      .map((c) => ({ name: c.name, crit: data.targets?.[c.name]?.[key] ?? null,
        wl: data.targets?.[c.name]?.wl, t: data.targets?.[c.name]?.t }))
      .filter((c) => c.crit !== null);
  }, [data, part]);

  const visibleCriteria = criteria.filter((c) => showC3 || Number(c.crit) !== 3);
  const dataCols = (data?.structure?.data || []).slice(0, 8);

  // severity rank for the per-event table: RED+ first, then RED, YELLOW, GREEN.
  // (lower number = more severe = nearer the top)
  const COLOR_RANK = { "RED +": 0, "RED+": 0, RED: 1, YELLOW: 2, ORANGE: 2, GREEN: 3 };
  const events = useMemo(() => {
    if (!data) return [];
    let evs = data.events.map((ev, i) => ({ ...ev, comp: ev[part], _i: i }));
    if (colorFilter === "RED") evs = evs.filter((e) => ["RED", "RED +", "RED+"].includes(e.comp?.color));
    if (colorFilter === "RY") evs = evs.filter((e) => ["RED", "RED +", "RED+", "YELLOW"].includes(e.comp?.color));
    if (gearFilter != null) {
      evs = evs.filter((e) => String(getChannel(e.channels, "gear new") ?? getChannel(e.channels, "Gear New") ?? "") === String(gearFilter));
    }
    // always order worst -> best; keep original order within the same color
    evs.sort((a, b) => {
      const ra = COLOR_RANK[a.comp?.color] ?? 4;
      const rb = COLOR_RANK[b.comp?.color] ?? 4;
      return ra !== rb ? ra - rb : a._i - b._i;
    });
    return evs;
  }, [data, part, colorFilter, gearFilter]);

  if (err) return <div style={{ padding: 30, color: "#a00" }}>{err}</div>;
  if (!data) return <div style={{ padding: 30, color: "#777" }}>Loading {name}…</div>;

  const res = data.result || {};
  const pr = res[part] || {};
  const counts = pr.counts || {};
  // per-SDV summary panel (Drivability/Responsiveness SUMMARY) from the backend
  const summ = (data.summary || {})[part] || null;
  const idxLabel = part === "driv" ? "Drivability Index" : "Responsiveness Index";
  const summaryLabel = part === "driv" ? "DRIVABILITY SUMMARY" : "RESPONSIVENESS SUMMARY";
  const idxCell = part === "driv" ? "J5" : "BQ5";

  const allCharts = (data.charts || []);
  // Build colored point sets per chart, using server-resolved ev.axis values
  // (alias-aware) and falling back to getChannel for older payloads.
  const buildPoints = (cx, cy) => {
    const pts = { RED: [], YELLOW: [], GREEN: [] };
    data.events.forEach((ev) => {
      const ax = ev.axis || {};
      let x = ax[cx]; if (x === undefined || x === null) x = Number(getChannel(ev.channels, cx));
      let y = ax[cy]; if (y === undefined || y === null) y = Number(getChannel(ev.channels, cy));
      x = Number(x); y = Number(y);
      const c = ev[part]?.color;
      if (!Number.isNaN(x) && !Number.isNaN(y) && pts[c]) {
        pts[c].push({ x, y, name: String(getChannel(ev.channels, "Sub Event Name") ?? "") });
      }
    });
    return pts;
  };

  return (
    <div style={{ padding: "8px 14px 50px", minWidth: 1100 }}>
      {/* toolbar */}
      <div className="xl-ribbon" style={{ border: "1px solid #D4D4D4", marginBottom: 8 }}>
        <button className="xl-btn primary" onClick={update} disabled={busy} data-testid="sdv-update-btn">
          {busy ? "UPDATING…" : "UPDATE"}
        </button>
        <button className="xl-btn" onClick={load} data-testid="sdv-targets-btn" title="Re-pull targets & recolor">TARGETS</button>
        <span className="sep" />
        <button className="xl-btn" style={colorFilter === "RED" ? { background: "#FBC7C7" } : null}
          onClick={() => setColorFilter(colorFilter === "RED" ? null : "RED")} data-testid="sdv-red-only-btn">RED ONLY</button>
        <button className="xl-btn" style={colorFilter === "RY" ? { background: "#FBE9A0" } : null}
          onClick={() => setColorFilter(colorFilter === "RY" ? null : "RY")} data-testid="sdv-yellow-red-btn">YELLOW + RED</button>
        <button className="xl-btn" onClick={() => { setColorFilter(null); setGearFilter(null); }} data-testid="sdv-filters-off-btn">FILTERS OFF</button>
        <span className="sep" />
        <span style={{ fontSize: 11, color: "#666" }}>Gear New =</span>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((g) => (
          <button key={g} className="xl-btn" style={{ padding: "2px 7px", ...(gearFilter === g ? { background: "#CCE4F7" } : {}) }}
            onClick={() => setGearFilter(gearFilter === g ? null : g)} data-testid={`sdv-gear-${g}`}>{g}</button>
        ))}
        <span className="sep" />
        <button className="xl-btn" onClick={() => setShowC3(!showC3)} data-testid="sdv-c3-btn">
          {showC3 ? "HIDE C3" : "Show C3"}
        </button>
        <span className="sep" />
        <button className="xl-btn" onClick={() => setPart(part === "driv" ? "dyn" : "driv")} data-testid="sdv-dyn-toggle">
          {part === "driv" ? "→ dyn" : "→ driv"}
        </button>
        <button className="xl-btn" onClick={() => openTab("HOME")} data-testid="sdv-home-btn">🏠 HOME</button>
        <button className="xl-btn" onClick={() => openTab("RATING")} data-testid="sdv-rating-btn">Q RATING</button>
        <span className="hint">{events.length}/{data.events.length} events shown</span>
      </div>

      {/* banner + summary panel (the DRIVABILITY SUMMARY) */}
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ flex: "0 0 auto" }}>
          <div style={{ background: TEAL, color: "#fff", fontWeight: 700, fontSize: 15, padding: "6px 14px" }} data-testid="sdv-banner">
            {name} — {summaryLabel}
          </div>

          {/* three priority gauges (P1/P2/P3 donuts) */}
          <div style={{ display: "flex", gap: 10, margin: "8px 0", justifyContent: "space-around" }} data-testid="sdv-gauges">
            {[1, 2, 3].map((p) => {
              const gg = summ?.gauges?.[p] || summ?.gauges?.[String(p)];
              return <PriorityGauge key={p} p={p} value={gg?.green_pct ?? null}
                target={gg?.target ?? null} nTotal={gg?.n_total ?? 0} />;
            })}
          </div>

          {/* color x priority breakdown table */}
          <table className="xl-grid" data-testid="sdv-summary-table">
            <thead>
              <tr>
                {["Color", "Priority (Px)", "Events", "% of total", "Breakpoints", "% of Px", "TARGETS"].map((h) => (
                  <th key={h} style={{ background: HBLUE, color: "#fff", fontSize: 11 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* TOTAL rows */}
              {[1, 2, 3].map((p, i) => (
                <tr key={"tot" + p} style={{ fontWeight: 700 }}>
                  {i === 0 && <td rowSpan={3} style={{ background: "#E6E6E6" }}>TOTAL</td>}
                  <td>P{p}</td>
                  {i === 0 && <td rowSpan={3} className="num">{summ?.table?.events?.total ?? counts.total ?? 0}</td>}
                  {i === 0 && <td rowSpan={3} className="num">100</td>}
                  <td className="num" data-testid={`bp-total-P${p}`}>{summ?.table?.breakpoints?.[p]?.total ?? summ?.table?.breakpoints?.[String(p)]?.total ?? 0}</td>
                  <td className="num">{fmtPct(summ?.table?.pct_total_prio?.[p] ?? summ?.table?.pct_total_prio?.[String(p)])}</td>
                  <td className="num" style={{ background: "#ddd" }}></td>
                </tr>
              ))}
              {/* Green / Yellow / Red blocks */}
              {[["GREEN", "green", "#007F00", "#fff"], ["YELLOW", "yellow", "#FFFF00", "#333"], ["RED", "red", "#FF0000", "#fff"]].map(
                ([COLOR, key, bg, fg]) =>
                  [1, 2, 3].map((p, i) => (
                    <tr key={COLOR + p}>
                      {i === 0 && (
                        <td rowSpan={3} style={{ background: bg, color: fg, fontWeight: 700 }}>
                          {COLOR[0] + COLOR.slice(1).toLowerCase()}
                        </td>
                      )}
                      <td>P{p}</td>
                      {i === 0 && <td rowSpan={3} className="num" data-testid={`events-${key}`}>{summ?.table?.events?.[key] ?? 0}</td>}
                      {i === 0 && <td rowSpan={3} className="num">{fmtPct(summ?.table?.pct_of_total?.[key])}</td>}
                      <td className="num">{summ?.table?.breakpoints?.[p]?.[key] ?? summ?.table?.breakpoints?.[String(p)]?.[key] ?? 0}</td>
                      <td className="num">{fmtPct(summ?.table?.[`pct_${key}`]?.[p] ?? summ?.table?.[`pct_${key}`]?.[String(p)])}</td>
                      <td className="num" style={{ background: "#F2F2F2" }}>
                        {(summ?.table?.[`target_${key}`]?.[p] ?? summ?.table?.[`target_${key}`]?.[String(p)]) ?? ""}
                      </td>
                    </tr>
                  ))
              )}
            </tbody>
          </table>

          {/* coverage rate achieved */}
          <table className="xl-grid" style={{ marginTop: 2 }} data-testid="sdv-coverage-table">
            <tbody>
              {[1, 2, 3].map((p, i) => {
                const cov = summ?.coverage?.[p] ?? summ?.coverage?.[String(p)];
                return (
                  <tr key={"cov" + p}>
                    {i === 0 && <td rowSpan={3} style={{ background: "#808080", color: "#fff", fontWeight: 700, width: 150 }}>Coverage rate achieved</td>}
                    <td style={{ width: 50 }}>P{p}</td>
                    <td className="num" data-testid={`coverage-P${p}`}
                      style={{ background: covColor(cov), width: 80 }}>{fmtPctFrac(cov)}</td>
                    {i === 0 && (
                      <td rowSpan={3} className="num" data-testid="coverage-overall"
                        style={{ background: covColor(summ?.coverage_overall), width: 90, fontWeight: 700, fontSize: 15 }}>
                        {fmtPctFrac(summ?.coverage_overall)}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ fontSize: 10, color: "#b06a00", marginTop: 3, maxWidth: 430 }}>
            ⚠ Coverage rate is provisional (needs the per-SDV population-grid
            denominator) — verify before reporting. Events, %, Breakpoints and
            % of Px are validated against the reference dataset.
          </div>
        </div>

        {/* index cells */}
        <div style={{ display: "flex", gap: 8 }}>
          <IndexCell label={idxLabel} addr={idxCell} value={summ?.index ?? pr.index} big setSelection={setSelection} testid="sdv-index" />
          <IndexCell label="Target Index" addr="K5" value={summ?.target_index ?? pr.target_index} setSelection={setSelection} testid="sdv-target-index" />
        </div>

        {/* status dots */}
        <table className="xl-grid">
          <thead>
            <tr><th style={{ background: HBLUE, color: "#fff" }} colSpan={3}>Status (current)</th></tr>
            <tr>{["P1", "P2", "P3"].map((p, i) => <th key={i}>{p}</th>)}</tr>
          </thead>
          <tbody>
            <tr>
              {[["status", 1], ["status", 2], ["status", 3]].map(([k, p], i) => {
                const st = pr[k]?.[String(p)] || "NONE";
                return (
                  <td key={i} style={{ textAlign: "center" }} data-testid={`sdv-${k}-P${p}`}>
                    <span style={{ color: { RED: "#FF0000", YELLOW: "#FFC000", ORANGE: "#FFC000", GREEN: "#00B050", NONE: "#BFBFBF" }[st], fontSize: 17 }}>●</span>
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>

      {/* event grid */}
      <div style={{ marginTop: 14, overflowX: "auto" }}>
        <table className="xl-grid" data-testid="sdv-event-table">
          <thead>
            {/* criticity row (row 5) */}
            <tr>
              <th colSpan={4 + dataCols.length} style={{ textAlign: "right", background: "#fff", border: "none" }}>Criticity →</th>
              {visibleCriteria.map((c) => (
                <th key={c.name} style={{ background: CRIT_FILL[Number(c.crit)] || "#eee" }} data-testid={`crit-${c.name}`}>
                  {c.crit}
                </th>
              ))}
              <th style={{ background: "#fff", border: "none" }} colSpan={2} />
            </tr>
            {/* header row 6 */}
            <tr>
              <th className="rowhead">#</th>
              <th>Criticality</th>
              <th>Priority</th>
              <th>Color</th>
              {dataCols.map((d) => <th key={d.name}>{d.name}</th>)}
              {visibleCriteria.map((c) => <th key={c.name} style={{ background: HBLUE, color: "#fff", minWidth: 56 }}>{c.name}</th>)}
              <th>Indice occurrencé</th>
              <th>DB ID</th>
            </tr>
            {/* waterline / target rows */}
            <tr style={{ background: "#FBE2D5" }}>
              <th colSpan={4 + dataCols.length} style={{ textAlign: "right" }}>Waterline</th>
              {visibleCriteria.map((c) => <td key={c.name} className="num">{fmt(c.wl)}</td>)}
              <td colSpan={2} />
            </tr>
            <tr style={{ background: "#A7D5AB" }}>
              <th colSpan={4 + dataCols.length} style={{ textAlign: "right" }}>Target</th>
              {visibleCriteria.map((c) => <td key={c.name} className="num">{fmt(c.t)}</td>)}
              <td colSpan={2} />
            </tr>
          </thead>
          <tbody>
            {events.map((ev, i) => (
              <EventRow key={ev.id} i={i + 1} ev={ev} dataCols={dataCols}
                criteria={visibleCriteria} setSelection={setSelection} />
            ))}
          </tbody>
        </table>
      </div>

      {/* charts — every configured chart + the Acceleration vs Speed view */}
      <div style={{ marginTop: 20, display: "flex", gap: 20, flexWrap: "wrap" }}>
        {allCharts.map((chart, ci) => {
          const xName = chart?.x || "Vehicle Speed";
          const yName = chart?.y || "AccelerationChassis";
          const points = buildPoints(xName, yName);
          const total = points.RED.length + points.YELLOW.length + points.GREEN.length;
          return (
            <div key={ci} style={{ width: 640, border: "1px solid #ccc", padding: 6 }}
                 data-testid={ci === 0 ? "sdv-chart" : `sdv-chart-${ci}`}>
              <div style={{ fontSize: 12, fontWeight: 700, color: TEAL, marginBottom: 2 }}>
                {chart?.name || `Graphique ${ci + 1}`} — {yName} vs {xName}
                {chart?.added ? <span style={{ color: "#888", fontWeight: 400 }}> (added)</span> : null}
                <span style={{ color: "#999", fontWeight: 400, float: "right" }}>{total} pts</span>
              </div>
              <ResponsiveContainer width="100%" height={320} minWidth={300}>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 18, left: 0 }}>
                  <CartesianGrid strokeDasharray="2 2" />
                  <XAxis type="number" dataKey="x" name={xName}
                    domain={[numOr(chart?.x_min, "auto"), numOr(chart?.x_max, "auto")]}
                    label={{ value: xName, position: "insideBottom", offset: -8, fontSize: 11 }} tick={{ fontSize: 10 }} />
                  <YAxis type="number" dataKey="y" name={yName}
                    domain={[numOr(chart?.y_min, "auto"), numOr(chart?.y_max, "auto")]}
                    tick={{ fontSize: 10 }} />
                  <Tooltip cursor={{ strokeDasharray: "3 3" }}
                    formatter={(v) => fmt(v, 2)} labelFormatter={() => ""} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {["GREEN", "YELLOW", "RED"].map((c) => (
                    <Scatter key={c} name={c} data={points[c]} fill={CELL_COLORS[c]}
                      stroke="#333" strokeWidth={0.6} />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
              <table className="xl-grid" style={{ marginTop: 4, fontSize: 11 }}>
                <tbody>
                  <tr><td className="rowhead">Abscisse</td><td>{xName}</td>
                      <td className="rowhead">X range</td><td>{String(chart?.x_min ?? "Auto")} → {String(chart?.x_max ?? "Auto")}</td></tr>
                  <tr><td className="rowhead">Ordonnée</td><td>{yName}</td>
                      <td className="rowhead">Y range</td><td>{String(chart?.y_min ?? "Auto")} → {String(chart?.y_max ?? "Auto")}</td></tr>
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function numOr(v, dflt) {
  const f = Number(v);
  return v === null || v === undefined || v === "" || Number.isNaN(f) || String(v).toLowerCase() === "automatique" ? dflt : f;
}

// "%" formatters for the summary panel
function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "";
  return Number(v).toFixed(1);
}
function fmtPctFrac(v) {  // coverage stored as a 0..1 fraction (provisional)
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const p = Math.max(0, Math.min(100, Math.round(Number(v) * 100)));
  return p + "%";
}
function covColor(v) {
  if (v === null || v === undefined) return "#fff";
  const p = Number(v);
  if (p >= 0.8) return "#92D050";   // good
  if (p >= 0.5) return "#FFFF00";   // medium
  return "#FF6B6B";                  // low
}

/**
 * Priority donut gauge (P1/P2/P3). Shows the green-coverage % as a filled arc
 * with a colored target ring. SVG, no dependencies.
 */
function PriorityGauge({ p, value, target, nTotal }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value));
  const R = 30, SW = 9, C = 40;            // radius, stroke width, center
  const circ = 2 * Math.PI * R;
  const fill = circ * (pct / 100);
  // color the fill by how it compares to target (green if >=target)
  const ringColor = target != null && pct >= target ? "#00B050"
    : pct >= 50 ? "#FFC000" : "#FF0000";
  return (
    <div style={{ textAlign: "center" }} data-testid={`sdv-gauge-P${p}`}>
      <svg width={C * 2} height={C * 2}>
        {/* track */}
        <circle cx={C} cy={C} r={R} fill="none" stroke="#E6E6E6" strokeWidth={SW} />
        {/* target tick (thin marker at the target angle) */}
        {target != null && (
          <circle cx={C} cy={C} r={R} fill="none" stroke="#999" strokeWidth={SW}
            strokeDasharray={`1 ${circ}`}
            strokeDashoffset={-(circ * (target / 100)) + circ / 4}
            transform={`rotate(-90 ${C} ${C})`} opacity="0.0" />
        )}
        {/* value arc */}
        <circle cx={C} cy={C} r={R} fill="none" stroke={ringColor} strokeWidth={SW}
          strokeDasharray={`${fill} ${circ - fill}`}
          strokeDashoffset={circ / 4}
          transform={`rotate(-90 ${C} ${C})`} strokeLinecap="round" />
        <text x={C} y={C - 2} textAnchor="middle" fontSize="15" fontWeight="700" fill="#1E2336">P{p}</text>
        <text x={C} y={C + 13} textAnchor="middle" fontSize="10" fill="#555">{value == null ? "—" : pct.toFixed(0) + "%"}</text>
      </svg>
      <div style={{ fontSize: 9.5, color: "#888" }}>
        target {target ?? "—"}{target != null ? "%" : ""}
      </div>
    </div>
  );
}

function IndexCell({ label, addr, value, big, setSelection, testid }) {
  return (
    <div onClick={() => setSelection({ addr, value: value ?? "" })} data-testid={testid}
      style={{ border: "2px solid " + TEAL, minWidth: 120, textAlign: "center", cursor: "pointer" }}>
      <div style={{ background: TEAL, color: "#fff", fontSize: 11, padding: "3px 8px" }}>{label}</div>
      <div style={{ fontSize: big ? 30 : 24, fontWeight: 700, padding: "8px 10px", color: "#1E2336" }}>
        {fmt(value)}
      </div>
    </div>
  );
}

function EventRow({ i, ev, dataCols, criteria, setSelection }) {
  const comp = ev.comp;
  const colorBg = {
    "RED +": "#990000", "RED+": "#990000",
    RED: "#FF0000", YELLOW: "#FFFF00", ORANGE: "#FFFF00", GREEN: "#00B050",
  }[comp?.color];
  return (
    <tr data-testid={`event-row-${ev.id.slice(0, 8)}`}>
      <td className="rowhead">{i}</td>
      <td style={{ fontSize: 11 }}>{comp?.criticity ?? "-"}</td>
      <td style={{ textAlign: "center" }}>{comp ? `P${comp.priority}` : "-"}</td>
      <td style={{ background: colorBg, color: comp?.color === "YELLOW" ? "#333" : "#fff", textAlign: "center", fontSize: 10.5 }}>
        {comp?.color ?? ""}
      </td>
      {dataCols.map((d) => {
        const v = getChannel(ev.channels, d.import || d.name) ?? getChannel(ev.channels, d.name);
        return <td key={d.name} className="num" onClick={() => setSelection({ addr: d.name, value: v ?? "" })}>{typeof v === "number" ? fmt(v, 1) : String(v ?? "")}</td>;
      })}
      {criteria.map((c) => {
        const v = getChannel(ev.channels, c.name);
        const cc = comp?.crit_colors?.[c.name] || comp?.crit_colors?.[c.name.replace(/\./g, "\u00b7")];
        const bg = { RED: "#FFC7CE", YELLOW: "#FFEB9C", GREEN: "#C6EFCE" }[cc];
        return (
          <td key={c.name} className="num" style={{ background: bg }}
            onClick={() => setSelection({ addr: c.name, value: v ?? "" })}>
            {typeof v === "number" ? fmt(v, 1) : String(v ?? "")}
          </td>
        );
      })}
      <td className="num" style={{ fontWeight: 700, color: (comp?.indice_occ ?? 0) < 0 ? "#c00" : "#070" }}>
        {fmt(comp?.indice_occ, 3)}
      </td>
      <td style={{ fontFamily: "monospace", fontSize: 10.5 }}>{ev.id.slice(0, 8)}</td>
    </tr>
  );
}
