import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/* Generic editable configuration sheets — the workbook's veryHidden layer.
   Every cell is editable; "Save sheet" writes the section back. */

export default function ConfigSheet({ sheetName, section }) {
  const [data, setData] = useState(null);
  const [extra, setExtra] = useState(null); // settings_global for SETTINGS
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const res = await api.get(`/config/${section}`);
    setData(res.data);
    if (section === "settings_blocks") {
      const g = await api.get("/config/settings_global");
      setExtra(g.data);
    }
    setDirty(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [section]);

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/config/${section}`, { data });
      if (section === "settings_blocks" && extra) {
        await api.put("/config/settings_global", { data: extra });
      }
      setDirty(false);
    } catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setSaving(false); }
  };

  const mutate = (fn) => { fn(); setData({ ...data }); setDirty(true); };
  const mutateExtra = (fn) => { fn(); setExtra({ ...extra }); setDirty(true); };

  if (!data) return <div style={{ padding: 30, color: "#777" }}>Loading {sheetName}…</div>;

  return (
    <div className="cfg-sheet">
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <h2 data-testid={`cfg-title-${section}`}>{sheetName}</h2>
        <button className="xl-btn primary" onClick={save} disabled={!dirty || saving} data-testid="cfg-save-btn">
          {saving ? "Saving…" : dirty ? "Save sheet" : "Saved"}
        </button>
        <button className="xl-btn" onClick={load} data-testid="cfg-reload-btn">Discard changes</button>
      </div>
      <div className="note">Every cell is editable — changes feed the rating engine.</div>
      {section === "settings_blocks" && <SettingsEditor data={data} extra={extra} mutate={mutate} mutateExtra={mutateExtra} />}
      {section === "definitions" && <DefinitionsEditor data={data} mutate={mutate} />}
      {section === "targets" && <TargetsEditor data={data} mutate={mutate} />}
      {section === "priorisation" && <PriorisationEditor data={data} mutate={mutate} />}
      {section === "configurations" && <ConfigurationsEditor data={data} mutate={mutate} />}
      {section === "catalog" && <CatalogEditor data={data} mutate={mutate} />}
      {section === "target_vehicle" && <TargetVehicleEditor data={data} mutate={mutate} />}
      {section === "calculs" && <CalculsEditor data={data} mutate={mutate} />}
      {section === "thresholds" && <ThresholdsEditor data={data} mutate={mutate} />}
      {section === "criticity" && <CriticityEditor data={data} mutate={mutate} />}
    </div>
  );
}

function Cell({ value, onChange, testid, width = 70 }) {
  return (
    <td style={{ padding: 0 }}>
      <input
        className="xl-cell-input" style={{ width, textAlign: "right", background: "#FDF7FA" }}
        value={value ?? ""} data-testid={testid}
        onChange={(e) => onChange(e.target.value === "" ? null : (Number.isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value)))}
      />
    </td>
  );
}

function TextCell({ value, onChange, width = 180, testid }) {
  return (
    <td style={{ padding: 0 }}>
      <input className="xl-cell-input" style={{ width, background: "#FDF7FA" }} value={value ?? ""}
        data-testid={testid} onChange={(e) => onChange(e.target.value)} />
    </td>
  );
}

/* ---------------- SETTINGS ---------------- */
function SettingsEditor({ data, extra, mutate, mutateExtra }) {
  const names = Object.keys(data);
  const [sel, setSel] = useState(names[0]);
  const b = data[sel];
  return (
    <div>
      <div className="cfg-toolbar">
        <label>SDV block :</label>
        <select value={sel} onChange={(e) => setSel(e.target.value)} data-testid="settings-sdv-select">
          {names.map((n) => <option key={n}>{n}</option>)}
        </select>
        <label style={{ marginLeft: 18 }}>WEIGHT</label>
        <input style={{ width: 60 }} value={b?.weight ?? ""} data-testid="settings-weight"
          onChange={(e) => mutate(() => { b.weight = Number(e.target.value) || 0; })} />
        <label>OVERALL MINI. NB. PTS.</label>
        <input style={{ width: 60 }} value={b?.overall_min_pts ?? ""} data-testid="settings-minpts"
          onChange={(e) => mutate(() => { b.overall_min_pts = Number(e.target.value) || 0; })} />
      </div>
      <div style={{ display: "flex", gap: 30, flexWrap: "wrap" }}>
        <div>
          <b style={{ fontSize: 12 }}>MILESTONES : PERCENTAGE</b>
          <table className="xl-grid">
            <thead><tr><th /><th>M1</th><th>M2</th><th>M3</th><th>M4</th></tr></thead>
            <tbody>
              {Object.keys(b?.pct || {}).map((k) => (
                <tr key={k}>
                  <td className="rowhead">%{k}</td>
                  {(b.pct[k] || []).map((v, i) => (
                    <Cell key={i} value={v} testid={`pct-${k}-${i}`}
                      onChange={(nv) => mutate(() => { b.pct[k][i] = nv; })} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <b style={{ fontSize: 12 }}>MILESTONES : MINI. NB. POINTS</b>
          <table className="xl-grid">
            <thead><tr><th /><th>M1</th><th>M2</th><th>M3</th><th>M4</th></tr></thead>
            <tbody>
              {Object.keys(b?.nmin || {}).map((k) => (
                <tr key={k}>
                  <td className="rowhead">N{k}</td>
                  {(b.nmin[k] || []).map((v, i) => (
                    <Cell key={i} value={v} testid={`nmin-${k}-${i}`}
                      onChange={(nv) => mutate(() => { b.nmin[k][i] = nv; })} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {extra && (
          <div>
            <b style={{ fontSize: 12 }}>COEFFICIENT PAR EVENEMENT (toutes SDV identiques)</b>
            <table className="xl-grid">
              <thead><tr><th /><th>RED</th><th>ORANGE</th><th>GREEN</th></tr></thead>
              <tbody>
                {["1", "2", "3"].map((p) => (
                  <tr key={p}>
                    <td className="rowhead">P{p}</td>
                    {["RED", "YELLOW", "GREEN"].map((c) => (
                      <Cell key={c} value={extra.coefficients[p][c]} testid={`coef-${p}-${c}`}
                        onChange={(nv) => mutateExtra(() => { extra.coefficients[p][c] = nv; })} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <table className="xl-grid" style={{ marginTop: 8 }}>
              <tbody>
                <tr><td className="rowhead">Zéro fictif (COEF1·WL + COEF2·T)</td>
                  <Cell value={extra.constants.COEF1} onChange={(v) => mutateExtra(() => { extra.constants.COEF1 = v; })} testid="coef1" />
                  <Cell value={extra.constants.COEF2} onChange={(v) => mutateExtra(() => { extra.constants.COEF2 = v; })} testid="coef2" />
                </tr>
                <tr><td className="rowhead">PUISS / GLOBALPUISS</td>
                  <Cell value={extra.constants.PUISS} onChange={(v) => mutateExtra(() => { extra.constants.PUISS = v; })} testid="puiss" />
                  <Cell value={extra.constants.GLOBALPUISS} onChange={(v) => mutateExtra(() => { extra.constants.GLOBALPUISS = v; })} testid="globalpuiss" />
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------------- DEFINITION SDV ---------------- */
const OPS = ["EGAL A", "DIFFERENT DE", "CONTIENT", "NE CONTIENT PAS",
  "INFERIEUR A", "INFERIEUR OU EGAL A", "SUPERIEUR A", "SUPERIEUR OU EGAL A"];

function DefinitionsEditor({ data, mutate }) {
  const [sel, setSel] = useState(0);
  const rule = data[sel];
  return (
    <div>
      <div className="cfg-toolbar">
        <label>Rule (ORDRE) :</label>
        <select value={sel} onChange={(e) => setSel(Number(e.target.value))} data-testid="def-rule-select">
          {data.map((r, i) => (
            <option key={i} value={i}>{r.order} — {r.sdv}{r.active ? "" : " (disabled)"}</option>
          ))}
        </select>
        <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <input type="checkbox" checked={!!rule?.active} data-testid="def-active"
            onChange={(e) => mutate(() => { rule.active = e.target.checked; })} />
          active
        </label>
        <button className="xl-btn" data-testid="def-add-rule"
          onClick={() => mutate(() => {
            data.push({ order: Math.max(...data.map((r) => r.order)) + 1, sdv: "NEW SDV", active: true, conditions: [] });
            setSel(data.length - 1);
          })}>+ Add rule</button>
        <button className="xl-btn" data-testid="def-del-rule"
          onClick={() => window.confirm("Delete this rule?") && mutate(() => { data.splice(sel, 1); setSel(0); })}>Delete rule</button>
      </div>
      {rule && (
        <>
          <div className="cfg-toolbar">
            <label>SDV :</label>
            <input style={{ width: 300 }} value={rule.sdv} data-testid="def-sdv-name"
              onChange={(e) => mutate(() => { rule.sdv = e.target.value; })} />
            <label>ORDRE :</label>
            <input style={{ width: 60 }} value={rule.order} data-testid="def-order"
              onChange={(e) => mutate(() => { rule.order = Number(e.target.value) || 0; })} />
          </div>
          <table className="xl-grid">
            <thead>
              <tr><th style={{ minWidth: 320 }}>COLONNE (Family, Channel)</th><th>CONDITION</th>
                <th style={{ minWidth: 200 }}>VALEUR</th><th>GROUPE</th><th /></tr>
            </thead>
            <tbody>
              {rule.conditions.map((c, i) => (
                <tr key={i}>
                  <TextCell value={c.column} width={320} testid={`def-col-${i}`}
                    onChange={(v) => mutate(() => { c.column = v; })} />
                  <td style={{ padding: 0 }}>
                    <select value={c.op} style={{ width: 170, border: "none", background: "#FDF7FA" }}
                      data-testid={`def-op-${i}`}
                      onChange={(e) => mutate(() => { c.op = e.target.value; })}>
                      {OPS.map((o) => <option key={o}>{o}</option>)}
                    </select>
                  </td>
                  <TextCell value={String(c.value ?? "")} width={200} testid={`def-val-${i}`}
                    onChange={(v) => mutate(() => { c.value = v; })} />
                  <Cell value={c.group} width={50} testid={`def-grp-${i}`}
                    onChange={(v) => mutate(() => { c.group = v; })} />
                  <td><button className="xl-btn" style={{ padding: "0 6px" }} data-testid={`def-del-cond-${i}`}
                    onClick={() => mutate(() => rule.conditions.splice(i, 1))}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="xl-btn" style={{ marginTop: 6 }} data-testid="def-add-cond"
            onClick={() => mutate(() => rule.conditions.push({ column: "Sous situation de vie, Sub Event Name", op: "EGAL A", value: "", group: 1 }))}>
            + Add condition
          </button>
          <div className="note" style={{ marginTop: 8 }}>
            Same GROUPE = OR ; different groups = AND ; value list with « ; » = OR ; first fully-matching rule wins (ORDRE).
          </div>
        </>
      )}
    </div>
  );
}

/* ---------------- TARGETS ---------------- */
function TargetsEditor({ data, mutate }) {
  const sdvs = [...new Set(data.map((r) => r.sdv))];
  const versions = [...new Set(data.map((r) => r.version))];
  const [sdv, setSdv] = useState(sdvs[0]);
  const [version, setVersion] = useState(versions[versions.length - 1]);
  const rows = data.filter((r) => r.sdv === sdv && r.version === version);
  return (
    <div>
      <div className="cfg-toolbar">
        <label>Operating Mode (SDV) :</label>
        <select value={sdv} onChange={(e) => setSdv(e.target.value)} data-testid="targets-sdv-select">
          {sdvs.map((s) => <option key={s}>{s}</option>)}
        </select>
        <label>Version Drive :</label>
        <select value={version} onChange={(e) => setVersion(e.target.value)} data-testid="targets-version-select">
          {versions.map((v) => <option key={v}>{v}</option>)}
        </select>
        <span className="note" style={{ margin: 0 }}>{data.length} target rows total</span>
      </div>
      <table className="xl-grid">
        <thead>
          <tr><th style={{ minWidth: 230 }}>Criteria</th><th>Range</th><th>Waterline</th><th>Target</th>
            <th>Responsiveness</th><th>Driveability</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const idx = data.indexOf(r);
            return (
              <tr key={idx}>
                <td>{r.criteria}</td>
                <td>{r.range}</td>
                <Cell value={r.wl} testid={`wl-${idx}`} onChange={(v) => mutate(() => { r.wl = v; })} />
                <Cell value={r.t} testid={`t-${idx}`} onChange={(v) => mutate(() => { r.t = v; })} />
                <Cell value={r.resp} testid={`resp-${idx}`} onChange={(v) => mutate(() => { r.resp = v; })} />
                <Cell value={r.driv} testid={`driv-${idx}`} onChange={(v) => mutate(() => { r.driv = v; })} />
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="note" style={{ marginTop: 6 }}>
        Driveability / Responsiveness columns are the per-criterion criticity (1 = C1 full weight, 2 = C2 half weight averaged, 3 = excluded).
      </div>
    </div>
  );
}

/* ---------------- CONFIGURATIONS SEETINGS (priorisation) ---------------- */
function CondTable({ title, all, on }) {
  const onSet = new Set((on || []).map((v) => String(v).trim().toUpperCase()));
  // include any enabled values not in the default list (e.g. unusual gearbox)
  const rows = [...all];
  (on || []).forEach((v) => { if (!rows.some((r) => String(r).toUpperCase() === String(v).toUpperCase())) rows.push(v); });
  return (
    <table className="xl-grid" style={{ fontSize: 11.5 }}>
      <thead><tr><th style={{ background: "#17375E", color: "#fff" }} colSpan={2}>{title}</th></tr></thead>
      <tbody>
        {rows.map((v) => {
          const active = onSet.has(String(v).trim().toUpperCase());
          return (
            <tr key={v}>
              <td style={{ minWidth: 92 }}>{v}</td>
              <td style={{ width: 28, textAlign: "center", background: active ? "#4FC3F7" : "transparent", color: active ? "#003" : "#bbb", fontWeight: 700 }}>
                {active ? "X" : ""}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PriorisationEditor({ data, mutate }) {
  const names = Object.keys(data);
  const [sel, setSel] = useState(names[0]);
  const cfgs = data[sel] || [];
  const cfg = cfgs[0];
  return (
    <div>
      <div className="cfg-toolbar">
        <label>SDV :</label>
        <select value={sel} onChange={(e) => setSel(e.target.value)} data-testid="prio-sdv-select">
          {names.map((n) => <option key={n}>{n}</option>)}
        </select>
        {cfg && <span style={{ fontWeight: 700 }}>{cfg.label}</span>}
      </div>
      {cfg && cfg.conditions && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11.5, color: "#666", marginBottom: 4 }}>
            This priority table is valid only for vehicles matching <b>all</b> of the
            conditions below (Engine type, Gearbox type, Number of gears, Area). Each
            SDV carries its own condition set.
          </div>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            <CondTable title="Engine type" all={["GASOLINE", "DIESEL"]} on={cfg.conditions.engine} />
            <CondTable title="Gearbox type" all={["AT", "EAT", "EDCT", "MT", "DCT", "CVT"]} on={cfg.conditions.gearbox} />
            <CondTable title="Number of gears" all={["5", "6", "7", "8", "9", "10"]} on={cfg.conditions.gears} />
            <CondTable title="Area" all={["EUROPE", "CHINA", "North America", "LATAM", "India", "World"]} on={cfg.conditions.area} />
          </div>
        </div>
      )}
      {!cfg ? <div className="note">UNAFFECTED — events of this SDV default to P3.</div> : (
        <table className="xl-grid">
          <thead>
            <tr>
              <th style={{ background: "#17375E", color: "#fff", whiteSpace: "nowrap" }}>{cfg.row_param || cfg.row_channel || "row"} \ {cfg.col_param || cfg.col_channel || "column"}</th>
              {(cfg.col_values || []).map((s, i) => <th key={i}>{s}</th>)}
            </tr>
          </thead>
          <tbody>
            {(cfg.rows || []).map((g, gi) => (
              <tr key={gi}>
                <td className="rowhead">{g.key}</td>
                {(g.priorities || []).map((p, pi) => (
                  <td key={pi} style={{ padding: 0, background: { 1: "#FFC7CE", 2: "#FFEB9C", 3: "#C6EFCE" }[p] }}>
                    <input className="xl-cell-input" style={{ width: 34, textAlign: "center", background: "transparent" }}
                      value={p ?? ""} data-testid={`prio-${gi}-${pi}`}
                      onChange={(e) => mutate(() => { g.priorities[pi] = e.target.value === "" ? null : Number(e.target.value); })} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="note" style={{ marginTop: 6 }}>
        {cfg && cfg.row_channel === "lever_transition"
          ? "Lookup: row = Lever Old→New transition ; column = last bound ≤ axis value → priority P1/P2/P3."
          : `Lookup: column = last ${cfg?.col_channel || "column"} bound ≤ value ; row = |${cfg?.row_channel || "row"}| band → priority P1/P2/P3.`}
      </div>
    </div>
  );
}

/* ---------------- CONFIGURATIONS (lists) ---------------- */
function ConfigurationsEditor({ data, mutate }) {
  return (
    <div style={{ display: "flex", gap: 30, flexWrap: "wrap" }}>
      <div>
        <b style={{ fontSize: 12 }}>MILESTONE (label → milestone n°)</b>
        <table className="xl-grid">
          <tbody>
            {Object.entries(data.milestones || {}).map(([k, v]) => (
              <tr key={k}>
                <td className="rowhead">{k}</td>
                <Cell value={v} width={50} testid={`ms-${k}`}
                  onChange={(nv) => mutate(() => { data.milestones[k] = nv; })} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <b style={{ fontSize: 12 }}>AREA</b>
        <table className="xl-grid"><tbody>
          {(data.areas || []).map((a, i) => (
            <tr key={i}><TextCell value={a} width={160} testid={`area-${i}`}
              onChange={(v) => mutate(() => { data.areas[i] = v; })} /></tr>
          ))}
        </tbody></table>
        <b style={{ fontSize: 12, display: "block", marginTop: 12 }}>Température (split Cold/Hot)</b>
        <table className="xl-grid"><tbody><tr>
          <Cell value={data.temperature_split} testid="temp-split"
            onChange={(v) => mutate(() => { data.temperature_split = v; })} />
        </tr></tbody></table>
      </div>
      <div>
        <b style={{ fontSize: 12 }}>MODES (code → name → family)</b>
        <table className="xl-grid">
          <tbody>
            {Object.entries(data.modes || {}).map(([k, m]) => (
              <tr key={k}>
                <td className="rowhead">{k}</td>
                <td>{m.name}</td><td>{m.family}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------------- SDV MANAGER (catalog) ---------------- */
function CatalogEditor({ data, mutate }) {
  return (
    <table className="xl-grid">
      <thead><tr><th>SDV</th><th>Group (use case)</th><th>Order</th></tr></thead>
      <tbody>
        {data.map((c, i) => (
          <tr key={i}>
            <TextCell value={c.name} width={280} testid={`cat-name-${i}`}
              onChange={(v) => mutate(() => { c.name = v; })} />
            <TextCell value={c.group} width={200} testid={`cat-group-${i}`}
              onChange={(v) => mutate(() => { c.group = v; })} />
            <Cell value={c.order} width={50} testid={`cat-order-${i}`}
              onChange={(v) => mutate(() => { c.order = v; })} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ---------------- TARGET VEHICLE ---------------- */
function TargetVehicleEditor({ data, mutate }) {
  return (
    <table className="xl-grid">
      <thead><tr><th>SdV</th><th>Drive version</th><th>TARGET VEHICLE</th><th>MODE</th>
        <th>Driveability Index</th><th>Responsiveness Index</th></tr></thead>
      <tbody>
        {data.rows.map((r, i) => (
          <tr key={i}>
            <td>{r.sdv}</td>
            <TextCell value={r.drive_version} width={70} testid={`tv-ver-${i}`}
              onChange={(v) => mutate(() => { r.drive_version = v; })} />
            <TextCell value={r.vehicle} width={150} testid={`tv-veh-${i}`}
              onChange={(v) => mutate(() => { r.vehicle = v; })} />
            <TextCell value={r.mode} width={70} testid={`tv-mode-${i}`}
              onChange={(v) => mutate(() => { r.mode = v; })} />
            <Cell value={r.driv} testid={`tv-driv-${i}`} onChange={(v) => mutate(() => { r.driv = v; })} />
            <Cell value={r.dyn} testid={`tv-dyn-${i}`} onChange={(v) => mutate(() => { r.dyn = v; })} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ---------------- Calculs ---------------- */
function CalculsEditor({ data, mutate }) {
  return (
    <div>
      <table className="xl-grid" style={{ marginBottom: 14 }}>
        <tbody>
          <tr><td className="rowhead">facteur Red+</td>
            <Cell value={data.facteur_redplus} testid="calc-redplus" onChange={(v) => mutate(() => { data.facteur_redplus = v; })} /></tr>
          <tr><td className="rowhead">coef orange Mainstream</td>
            <Cell value={data.coef_orange_mainstream} testid="calc-mainstream" onChange={(v) => mutate(() => { data.coef_orange_mainstream = v; })} /></tr>
          <tr><td className="rowhead">coef orange Premium</td>
            <Cell value={data.coef_orange_premium} testid="calc-premium" onChange={(v) => mutate(() => { data.coef_orange_premium = v; })} /></tr>
        </tbody>
      </table>
      <table className="xl-grid">
        <thead><tr><th style={{ minWidth: 240 }}>SDV</th><th>taux (occurrence)</th><th>P1 rate</th><th>P2 rate</th><th>P3 rate</th></tr></thead>
        <tbody>
          {Object.entries(data.sdv || {}).map(([name, r]) => (
            <tr key={name}>
              <td>{name}</td>
              <Cell value={r.taux} width={110} testid={`taux-${name.slice(0, 10)}`}
                onChange={(v) => mutate(() => { r.taux = v; })} />
              {[0, 1, 2].map((i) => (
                <Cell key={i} value={r.p_rates?.[i]} width={90} testid={`prate-${name.slice(0, 8)}-${i}`}
                  onChange={(v) => mutate(() => { r.p_rates[i] = v; })} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------- Graph_status thresholds ---------------- */
function ThresholdsEditor({ data, mutate }) {
  return (
    <div style={{ display: "flex", gap: 40, flexWrap: "wrap" }}>
      {["driv", "dyn"].map((part) => (
        <div key={part}>
          <b style={{ fontSize: 13 }}>{part === "driv" ? "DRIVABILITY" : "RESPONSIVENESS"}</b>
          <table className="xl-grid" style={{ marginTop: 4 }}>
            <thead><tr><th /><th>M1</th><th>M2</th><th>M3</th><th>M4</th></tr></thead>
            <tbody>
              {Object.entries(data[part] || {}).map(([k, arr]) => (
                <tr key={k}>
                  <td className="rowhead">{k}</td>
                  {(arr || []).map((v, i) => (
                    <Cell key={i} value={v} testid={`thr-${part}-${k}-${i}`}
                      onChange={(nv) => mutate(() => { data[part][k][i] = nv; })} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

/* ---------------- cfg_criticity ---------------- */
function CriticityEditor({ data, mutate }) {
  return (
    <div>
      <table className="xl-grid">
        <thead><tr><th>Drive rating</th><th>P1</th><th>P2</th><th>P3</th></tr></thead>
        <tbody>
          {Object.entries(data.table || {}).map(([level, arr]) => (
            <tr key={level}>
              <td className="rowhead">{level}</td>
              {arr.map((v, i) => (
                <Cell key={i} value={v} testid={`crit-${level}-${i}`}
                  onChange={(nv) => mutate(() => { data.table[level][i] = nv; })} />
              ))}
            </tr>
          ))}
          <tr>
            <td className="rowhead">Orange/yellow threshold</td>
            {(data.seuil || []).map((v, i) => (
              <Cell key={i} value={v} testid={`seuil-${i}`}
                onChange={(nv) => mutate(() => { data.seuil[i] = nv; })} />
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
