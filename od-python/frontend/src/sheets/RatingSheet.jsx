import { useEffect, useState } from "react";
import { api, fmt, DOT_COLORS, VERDICT_COLORS } from "@/lib/api";
import { useWorkbook } from "@/components/Workbook";

const HEADBLUE = "#17375E";

export default function RatingSheet() {
  const { openTab, refresh, setSelection } = useWorkbook();
  const [data, setData] = useState(null);
  const [maskEmpty, setMaskEmpty] = useState(true);
  const [busy, setBusy] = useState(null);
  const [tProg, setTProg] = useState(null);   // {percent, phase} while scoring targets
  const [improvements, setImprovements] = useState(["", "", ""]);  // user-editable

  const load = async () => {
    const res = await api.get("/rating");
    setData(res.data);
  };
  useEffect(() => { load(); }, []);

  const calculate = async () => {
    setBusy("calc");
    try { await api.post("/rating/calculate"); await load(); await refresh(); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusy(null); }
  };

  const setAsTarget = async () => {
    setBusy("target");
    setTProg({ percent: 0, phase: "Starting…" });
    try {
      const start = await api.post("/rating/set-as-target/start");
      if (start.data?.already_running) { /* fall through to poll */ }
      // poll progress until done
      // eslint-disable-next-line no-constant-condition
      while (true) {
        await new Promise((r) => setTimeout(r, 700));
        const p = (await api.get("/rating/set-as-target/progress")).data;
        setTProg({ percent: p.percent || 0, phase: p.phase || "" });
        if (p.error) throw new Error(p.error);
        if (!p.running && p.done) break;
      }
      await load(); await refresh();
      const final = (await api.get("/rating/set-as-target/progress")).data;
      if (final.error) throw new Error(final.error);
      if (final.failed?.length) {
        alert(`${final.applied ?? 0} of ${(final.applied ?? 0) + final.failed.length} targets scored.\n\nCould not score:\n`
          + final.failed.map((f) => `• ${f.target}: ${f.detail}`).join("\n"));
      }
    } catch (e) {
      // 400 = no targets selected for this project
      alert(e.response?.data?.detail || e.message);
    } finally { setBusy(null); setTProg(null); }
  };

  const saveToDatabase = async () => {
    setBusy("save");
    try {
      const res = await api.post("/db/save");
      alert(`Project ${res.data.action} to the database.\n\n${res.data.uniquename}`);
    } catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusy(null); }
  };

  if (!data) return <div style={{ padding: 30, color: "#777" }}>Loading RATING…</div>;
  const { project, global: glob, rows, catalog, comparisons = {}, targets = [], target_globals = {} } = data;
  const resultBySdv = Object.fromEntries((rows || []).map((r) => [r.name, r]));
  // current project vehicle name (the vehicle being tested) — shown as the first
  // comparison column. There is NO automatic "primary target": target columns are
  // exactly the vehicles the user selected and then pressed "Set as target".
  const currentName = project?.name_code || "Current vehicle";
  const extraVehicles = (targets || []).filter((v) => v && v !== currentName);
  const compFor = (vehicle, sdvName, part) => {
    const veh = comparisons[vehicle];
    if (!veh) return null;
    const row = veh[String(sdvName).toUpperCase()];
    return row ? row[part] : null;
  };

  // build catalog-ordered display rows with group bands
  const groups = [];
  (catalog || []).forEach((c) => {
    let g = groups.find((x) => x.name === c.group);
    if (!g) { g = { name: c.group, sdvs: [] }; groups.push(g); }
    g.sdvs.push(c.name);
  });

  // (Top Areas for Improvement are intentionally left blank for the engineer
  // to fill in manually — no auto-fill from worst SDVs.)

  return (
    <div style={{ padding: "10px 16px 40px", minWidth: 1280 }}>
      {/* title */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 700, whiteSpace: "pre-line", flex: 1 }} data-testid="rating-title">
          DRIVABILITY VERIFICATION — SCORECARD{"\n"}
          <span style={{ fontSize: 10.5, fontWeight: 400, color: "#666" }}>
            (reflects only vehicle drivability under standard ambient conditions at sea level.
            Cold/hot, grades or high altitude behaviour is not covered by this status)
          </span>
        </div>
        <div style={{ color: "#c00", fontWeight: 700, fontSize: 13 }}>Confidential</div>
      </div>

      {/* meta + actions */}
      <div style={{ display: "flex", gap: 24, margin: "10px 0", alignItems: "flex-start", flexWrap: "wrap" }}>
        {extraVehicles.length > 0 && (
          <div style={{ fontSize: 11, color: "#070", padding: "4px 8px",
            background: "#eef8ee", border: "1px solid #b8ddb8", borderRadius: 3 }}
            data-testid="rating-target-count">
            Comparison targets: {extraVehicles.join(", ")}
          </div>
        )}
        <table className="xl-grid">
          <tbody>
            <tr><td className="rowhead">Application :</td><td data-testid="rating-application">{project?.name_code || "-"}</td></tr>
            <tr><td className="rowhead">Stage :</td><td>{project?.odriv_milestone || "-"}</td></tr>
            <tr><td className="rowhead">Odriv Version :</td><td>{data.version}</td></tr>
          </tbody>
        </table>
        <table className="xl-grid">
          <tbody>
            <tr><td className="rowhead" rowSpan={3} style={{ verticalAlign: "top" }}>Top Areas for Improvement:</td>
              <td data-testid="rating-improve-1" style={{ padding: 0 }}>
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{ padding: "0 4px", color: "#555" }}>1.</span>
                  <input value={improvements[0]}
                    onChange={(e) => setImprovements((a) => [e.target.value, a[1], a[2]])}
                    placeholder="type here…"
                    style={{ border: "none", outline: "none", width: "100%", background: "transparent", fontSize: 12, padding: "3px 2px" }} />
                </div></td></tr>
            <tr><td data-testid="rating-improve-2" style={{ padding: 0 }}>
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{ padding: "0 4px", color: "#555" }}>2.</span>
                  <input value={improvements[1]}
                    onChange={(e) => setImprovements((a) => [a[0], e.target.value, a[2]])}
                    placeholder="type here…"
                    style={{ border: "none", outline: "none", width: "100%", background: "transparent", fontSize: 12, padding: "3px 2px" }} />
                </div></td></tr>
            <tr><td data-testid="rating-improve-3" style={{ padding: 0 }}>
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{ padding: "0 4px", color: "#555" }}>3.</span>
                  <input value={improvements[2]}
                    onChange={(e) => setImprovements((a) => [a[0], a[1], e.target.value])}
                    placeholder="type here…"
                    style={{ border: "none", outline: "none", width: "100%", background: "transparent", fontSize: 12, padding: "3px 2px" }} />
                </div></td></tr>
          </tbody>
        </table>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button className="xl-btn primary" onClick={calculate} disabled={!!busy} data-testid="rating-calculate-btn">
            {busy === "calc" ? "Calculating…" : "CALCULATE RATING"}
          </button>
          <button className="xl-btn" onClick={setAsTarget} disabled={!!busy || !glob} data-testid="rating-set-as-target-btn"
            title="Read & score the target vehicle(s) selected in New Project, and show them on the graph">
            {busy === "target" ? "Calculating target(s)…" : "CALCULATE TARGET"}
          </button>
          <button className="xl-btn" onClick={saveToDatabase} disabled={!!busy || !glob} data-testid="rating-save-db-btn"
            title="Save this processed project to the shared database">
            {busy === "save" ? "Saving…" : "💾 SAVE TO DATABASE"}
          </button>
          <label className="xl-btn" style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <input type="checkbox" checked={maskEmpty} onChange={(e) => setMaskEmpty(e.target.checked)}
              data-testid="rating-mask-empty" />
            Mask empty SdV
          </label>
        </div>
      </div>

      {/* the two risk blocks */}
      <RiskBlock label={"DRIVABILITY\ncomfort/disturbances (bump, shock, jerk, …)"} g={glob?.driv} currentName={currentName} testid="driv" setSelection={setSelection} extraVehicles={extraVehicles} comparisons={comparisons} targetGlobals={target_globals} part="driv" />
      <RiskBlock label={"RESPONSIVENESS\nPerformance feel (response delay, vehicle Agility, …)"} g={glob?.dyn} currentName={currentName} testid="dyn" setSelection={setSelection} extraVehicles={extraVehicles} comparisons={comparisons} targetGlobals={target_globals} part="dyn" />

      {/* use-case table */}
      <table className="xl-grid" style={{ marginTop: 18 }} data-testid="rating-table">
        <thead>
          <tr>
            <th rowSpan={3} style={{ minWidth: 230, background: HEADBLUE, color: "#fff" }}>USE CASE</th>
            <th colSpan={5 + extraVehicles.length} style={{ background: HEADBLUE, color: "#fff" }}>Drivability</th>
            <th colSpan={5 + extraVehicles.length} style={{ background: HEADBLUE, color: "#fff" }}>Responsiveness</th>
          </tr>
          <tr>
            <th colSpan={3} style={{ background: HEADBLUE, color: "#fff" }}>Current Status</th>
            <th style={{ background: HEADBLUE, color: "#fff" }}>Driveability Index<br /><span style={{ fontSize: 9, fontWeight: 400 }}>{currentName}</span></th>
            {extraVehicles.map((v) => <th key={"dh-" + v} style={{ background: "#ECECEC", fontSize: 11 }}>{v}</th>)}
            <th style={{ background: HEADBLUE, color: "#fff", minWidth: 150 }}>Drivability Lowest Events</th>
            <th colSpan={3} style={{ background: HEADBLUE, color: "#fff" }}>Current Status</th>
            <th style={{ background: HEADBLUE, color: "#fff" }}>Responsiveness Index<br /><span style={{ fontSize: 9, fontWeight: 400 }}>{currentName}</span></th>
            {extraVehicles.map((v) => <th key={"rh-" + v} style={{ background: "#ECECEC", fontSize: 11 }}>{v}</th>)}
            <th style={{ background: HEADBLUE, color: "#fff", minWidth: 150 }}>Responsiveness Lowest Events</th>
          </tr>
          <tr>
            {["P1", "P2", "P3"].map((p, i) => <th key={"d" + i}>{p}</th>)}
            {Array.from({ length: 2 + extraVehicles.length }).map((_, i) => <th key={"de" + i} />)}
            {["P1", "P2", "P3"].map((p, i) => <th key={"r" + i}>{p}</th>)}
            {Array.from({ length: 2 + extraVehicles.length }).map((_, i) => <th key={"re" + i} />)}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const visible = g.sdvs.filter((s) => !maskEmpty || resultBySdv[s]);
            if (!visible.length) return null;
            return [
              <tr key={g.name}>
                <td colSpan={11 + extraVehicles.length * 2} style={{ background: HEADBLUE, color: "#fff", fontWeight: 700 }} data-testid={`rating-group-${g.name}`}>
                  {g.name}
                </td>
              </tr>,
              ...visible.map((sdvName) => {
                const r = resultBySdv[sdvName];
                return (
                  <SdvRow key={sdvName} name={sdvName} r={r} openTab={openTab}
                    extraVehicles={extraVehicles} compFor={compFor} />
                );
              }),
            ];
          })}
        </tbody>
      </table>

      {tProg && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9999 }}
          data-testid="target-progress-overlay">
          <div style={{ background: "#fff", borderRadius: 8, padding: "26px 30px",
            width: 480, boxShadow: "0 12px 40px rgba(0,0,0,0.3)" }}>
            <div style={{ fontWeight: 700, fontSize: 15, color: "#1E2336", marginBottom: 4 }}>
              Scoring target vehicle(s)…
            </div>
            <div style={{ fontSize: 12, color: "#666", marginBottom: 16, minHeight: 32 }}
              data-testid="target-progress-phase">
              {tProg.phase || "Working…"}
            </div>
            <div style={{ background: "#E6E8EE", borderRadius: 20, height: 22, overflow: "hidden", position: "relative" }}>
              <div style={{ width: `${tProg.percent}%`, height: "100%",
                background: "linear-gradient(90deg,#2E6FC5,#3F8AE0)", borderRadius: 20,
                transition: "width 0.3s ease" }} data-testid="target-progress-bar" />
              <div style={{ position: "absolute", inset: 0, display: "flex",
                alignItems: "center", justifyContent: "center", fontSize: 12,
                fontWeight: 700, color: tProg.percent > 50 ? "#fff" : "#1E2336" }}>
                {tProg.percent}%
              </div>
            </div>
            <div style={{ fontSize: 10.5, color: "#999", marginTop: 12, textAlign: "center", lineHeight: 1.5 }}>
              Target vehicles are scored from the local database. The first time
              a vehicle is scored it is cached, so selecting it again is instant.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function RiskMarkerBar({ axis, g, extraTargets = [] }) {
  // axis "index": 0..100 normalized %, zones red|yellow|green at yellow/green mins;
  //               markers placed at the precomputed normalized positions.
  // axis "taux":  0..full_scale %, zones green|yellow|red; tested marker only.
  const bar = g?.bar;
  if (!bar) return null;
  const W = 560, BARH = 22, PAD_TOP = 12, PAD_BOT = 12;
  const H = BARH + PAD_TOP + PAD_BOT;
  const midY = PAD_TOP + BARH / 2;
  let zones, toX, testedX, targetX;
  if (axis === "index") {
    const yMin = bar.index_yellow_min, gMin = bar.index_green_min; // 55, 71
    zones = [
      { from: 0, to: yMin, color: "#FF0000" },
      { from: yMin, to: gMin, color: "#FFFF00" },
      { from: gMin, to: 100, color: "#00B050" },
    ];
    toX = (v) => Math.max(0, Math.min(100, v)) / 100 * W;
    testedX = bar.tested_index_pos != null ? toX(bar.tested_index_pos) : null;
    targetX = bar.target_index_pos != null ? toX(bar.target_index_pos) : null;
  } else {
    const fs = bar.taux_full_scale || 12;
    const gMax = bar.taux_green_max, yMax = bar.taux_yellow_max; // 3, 9
    zones = [
      { from: 0, to: gMax, color: "#00B050" },
      { from: gMax, to: yMax, color: "#FFFF00" },
      { from: yMax, to: fs, color: "#FF0000" },
    ];
    toX = (v) => Math.max(0, Math.min(fs, v)) / fs * W;
    testedX = bar.tested_taux_pos != null ? toX(bar.tested_taux_pos) : null;
    targetX = null; // taux target not computed
  }
  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      {zones.map((z, i) => (
        <rect key={i} x={toX(z.from)} y={PAD_TOP} width={Math.max(0, toX(z.to) - toX(z.from))}
          height={BARH} fill={z.color} stroke="#fff" strokeWidth="0.5" />
      ))}
      {/* zone boundary labels above the bar */}
      {axis === "index" && (
        <>
          <text x={toX(bar.index_yellow_min)} y={8} fontSize="8.5" fill="#444" textAnchor="middle">{bar.index_yellow_min}%</text>
          <text x={toX(bar.index_green_min)} y={8} fontSize="8.5" fill="#444" textAnchor="middle">{bar.index_green_min}%</text>
        </>
      )}
      {axis === "taux" && (
        <>
          <text x={toX(bar.taux_yellow_max)} y={H - 2} fontSize="8.5" fill="#444" textAnchor="middle">{bar.taux_yellow_max}%</text>
          <text x={toX(bar.taux_green_max)} y={H - 2} fontSize="8.5" fill="#444" textAnchor="middle">{bar.taux_green_max}%</text>
        </>
      )}
      {/* target triangle (magenta), vertically centered on the bar */}
      {targetX != null && (
        <polygon points={`${targetX},${midY - 7} ${targetX - 7},${midY + 7} ${targetX + 7},${midY + 7}`}
          fill="#FF00FF" stroke="#000" strokeWidth="0.6" />
      )}
      {/* extra comparison targets (other triangles) — on both index & taux bars */}
      {extraTargets.map((t, i) =>
        t.pos != null ? (
          <polygon key={i}
            points={`${toX(t.pos)},${midY - 7} ${toX(t.pos) - 7},${midY + 7} ${toX(t.pos) + 7},${midY + 7}`}
            fill={t.color} stroke="#000" strokeWidth="0.6" />
        ) : null)}
      {/* tested diamond (black), vertically centered on the bar */}
      {testedX != null && (
        <polygon points={`${testedX},${midY - 8} ${testedX - 7},${midY} ${testedX},${midY + 8} ${testedX + 7},${midY}`}
          fill="#000" />
      )}
    </svg>
  );
}

// fixed marker colours: current test = black (handled separately), then targets
// in order: 1st = red, 2nd = light blue, 3rd = purple (extra ones cycle).
const TARGET_TRI_COLORS = ["#E00000", "#36A2EB", "#8E44AD", "#00897B"];

function RiskBlock({ label, g, currentName, testid, setSelection, extraVehicles = [], comparisons = {}, targetGlobals = {}, part = "driv" }) {
  // build extra-target marker positions on the index bar (normalized ^puiss)
  const gp = 5;
  const posKey = part === "dyn" ? "dyn_pos" : "driv_pos";
  const idxKey = part === "dyn" ? "dyn" : "driv";
  // first column = the CURRENT project vehicle (its own global index + black
  // diamond marker). Remaining columns = the vehicles the user selected and
  // scored via "Set as target" (colored triangles). No default benchmark.
  const cmpCols = [
    { name: currentName, isTarget: false, isCurrent: true,
      idx: g?.index, pos: g?.bar?.tested_index_pos, color: "#000",
      taux: g?.rate_low, tauxPos: g?.bar?.tested_taux_pos },
    ...extraVehicles.map((v, i) => {
      const tg = targetGlobals[v];
      const tauxKey = part === "dyn" ? "rate_low_dyn" : "rate_low_driv";
      const tauxPosKey = part === "dyn" ? "taux_dyn_pos" : "taux_driv_pos";
      return { name: v, isTarget: true, isCurrent: false,
        idx: tg ? tg[idxKey] : null,
        pos: tg ? tg[posKey] : null,
        taux: tg ? tg[tauxKey] : null,
        tauxPos: tg ? tg[tauxPosKey] : null,
        color: TARGET_TRI_COLORS[i % TARGET_TRI_COLORS.length] };
    }),
  ];
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ textAlign: "center", fontSize: 11.5, fontWeight: 700, marginBottom: 3 }}>
        Risk assessment for customer complaints
      </div>
      <div style={{ display: "flex", alignItems: "stretch" }}>
        {/* left label box */}
        <div style={{ background: "#fff", border: "1px solid #999", padding: "8px 12px", width: 250, whiteSpace: "pre-line", fontWeight: 700, fontSize: 12.5, display: "flex", alignItems: "center" }}>
          {label}
        </div>
        {/* verdict chip */}
        <div data-testid={`verdict-${testid}-current`}
          style={{ width: 110, background: VERDICT_COLORS[g?.verdict] || "#777", color: "#fff", fontWeight: 700, fontSize: 12, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
          {g?.verdict || "—"}
        </div>
        {/* row labels + bars */}
        <div style={{ display: "flex", flexDirection: "column", border: "1px solid #ccc", borderLeft: "none" }} data-testid={`riskbar-${testid}`}>
          <div style={{ display: "flex", alignItems: "center", borderBottom: "1px solid #ddd" }}>
            <div style={{ width: 90, fontSize: 10.5, color: "#333", textAlign: "center", background: "#F2F2F2", alignSelf: "stretch", display: "flex", alignItems: "center", justifyContent: "center", borderRight: "1px solid #ddd" }}>index</div>
            <RiskMarkerBar axis="index" g={g}
              extraTargets={cmpCols.filter((c) => c.isTarget).map((c) => ({ pos: c.pos, color: c.color }))} />
          </div>
          <div style={{ display: "flex", alignItems: "center" }}>
            <div style={{ width: 90, fontSize: 9.5, color: "#333", textAlign: "center", background: "#F2F2F2", alignSelf: "stretch", display: "flex", alignItems: "center", justifyContent: "center", borderRight: "1px solid #ddd" }}>Weighted % of events below target</div>
            <RiskMarkerBar axis="taux" g={g}
              extraTargets={cmpCols.filter((c) => c.isTarget && c.tauxPos != null).map((c) => ({ pos: c.tauxPos, color: c.color }))} />
          </div>
        </div>
        {/* comparison table on the right (one column per vehicle) */}
        <table className="xl-grid" style={{ borderLeft: "none", fontSize: 10.5 }}>
          <thead>
            {/* marker legend row: same symbol+color as the bar marker, so the
                user can match each marker to its vehicle column */}
            <tr>
              {cmpCols.map((c, i) => (
                <th key={"mk" + i} style={{ background: "#fff", borderBottom: "none", padding: "1px 4px", textAlign: "center" }}
                  data-testid={`riskcmp-${testid}-marker-${c.isCurrent ? "tested" : c.name}`}>
                  <span style={{ color: c.color, fontSize: 13, lineHeight: 1 }}>
                    {c.isCurrent ? "◆" : "▲"}
                  </span>
                </th>
              ))}
            </tr>
            <tr>
              {cmpCols.map((c, i) => (
                <th key={i} style={{ background: "#808080", color: "#fff", minWidth: 88, fontSize: 9.5, padding: "2px 4px" }}>
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {cmpCols.map((c, i) => {
                // The cell shows the NORMALISED bar-position % (= (index/100)^
                // GLOBALPUISS * 100), the same value that places the marker on the
                // red/yellow/green bar — NOT the raw index. We match that.
                const posVal = c.isCurrent ? g?.bar?.tested_index_pos : c.pos;
                return (
                  <td key={i} className="num" style={{ background: "#D9D9D9", fontWeight: c.isCurrent ? 700 : 400 }}
                    data-testid={c.isCurrent ? `riskcmp-${testid}-idx-tested` : `riskcmp-${testid}-idx-${c.name}`}
                    title={(c.isCurrent ? g?.index : c.idx) != null ? `raw index ${fmt(c.isCurrent ? g?.index : c.idx)}` : undefined}>
                    {posVal != null ? posVal.toFixed(2) + "%" : "—"}
                  </td>
                );
              })}
            </tr>
            <tr>
              {cmpCols.map((c, i) => {
                const tv = c.isCurrent ? g?.bar?.tested_taux_pos : c.tauxPos;
                return (
                  <td key={i} className="num" style={{ background: "#D9D9D9", fontWeight: c.isCurrent ? 700 : 400 }}
                    data-testid={c.isCurrent ? `riskcmp-${testid}-taux-tested` : `riskcmp-${testid}-taux-${c.name}`}>
                    {tv != null ? tv.toFixed(2) + "%" : "—"}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Dot({ status }) {
  return (
    <span style={{ color: DOT_COLORS[status || "NONE"], fontSize: 15, lineHeight: 1 }}>●</span>
  );
}

function SdvRow({ name, r, openTab, extraVehicles = [], compFor }) {
  const d = r?.driv;
  const dy = r?.dyn;
  const dots = (part, key) =>
    [1, 2, 3].map((p) => (
      <td key={key + p} style={{ textAlign: "center" }}>
        <Dot status={part ? part[key]?.[String(p)] : "NONE"} />
      </td>
    ));
  return (
    <tr data-testid={`rating-row-${name}`} style={{ background: r ? "#fff" : "#FAFAFA" }}>
      <td>
        <span
          onClick={() => r && openTab(name)}
          style={{ color: r ? "#0563C1" : "#999", textDecoration: r ? "underline" : "none", cursor: r ? "pointer" : "default", paddingLeft: 14 }}
          data-testid={`rating-link-${name}`}
        >
          {name}
        </span>
      </td>
      {dots(d, "status")}
      <td className="num" data-testid={`driv-index-${name}`}>{fmt(d?.index)}</td>
      {extraVehicles.map((v) => (
        <td key={"dc-" + v} className="num" style={{ background: "#F4F4F4" }}
          data-testid={`driv-cmp-${v}-${name}`}>{fmt(compFor ? compFor(v, name, "driv") : null)}</td>
      ))}
      <td style={{ fontSize: 11 }}>{d?.lowest_event || ""}</td>
      {dots(dy, "status")}
      <td className="num">{fmt(dy?.index)}</td>
      {extraVehicles.map((v) => (
        <td key={"rc-" + v} className="num" style={{ background: "#F4F4F4" }}
          data-testid={`resp-cmp-${v}-${name}`}>{fmt(compFor ? compFor(v, name, "dyn") : null)}</td>
      ))}
      <td style={{ fontSize: 11 }}>{dy?.lowest_event || ""}</td>
    </tr>
  );
}
