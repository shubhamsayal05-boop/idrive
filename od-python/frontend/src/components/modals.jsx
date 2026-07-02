import { useEffect, useRef, useState } from "react";
import { api, fmt } from "@/lib/api";

export function Modal({ title, onClose, children, footer, wide }) {
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={wide ? { minWidth: 760 } : undefined}>
        <div className="modal-title">
          <span>{title}</span>
          <span className="x" onClick={onClose} data-testid="modal-close">✕</span>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

/* ---------------- unlock (password = UNLOCK, like the original) -------- */
export function UnlockModal({ onClose, onUnlock }) {
  const [pwd, setPwd] = useState("");
  const [err, setErr] = useState(false);
  const submit = () => {
    if (pwd.trim().toUpperCase() === "UNLOCK") onUnlock();
    else setErr(true);
  };
  return (
    <Modal
      title="Unlock sheets" onClose={onClose}
      footer={
        <>
          <button className="xl-btn" onClick={onClose} data-testid="unlock-cancel">Cancel</button>
          <button className="xl-btn primary" onClick={submit} data-testid="unlock-submit">OK</button>
        </>
      }
    >
      <div className="form-row">
        <label>Password</label>
        <input
          type="password" value={pwd} autoFocus data-testid="unlock-password"
          onChange={(e) => { setPwd(e.target.value); setErr(false); }}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
      </div>
      <div style={{ fontSize: 11, color: err ? "#c00" : "#777" }}>
        {err ? "Wrong password." : "Hint: the configured access password."}
      </div>
    </Modal>
  );
}

/* ---------------- new project ---------------- */
export function NewProjectModal({ onClose, onCreated, lists }) {
  const [form, setForm] = useState({
    name_code: "", droopy: "", software_milestone: "QG6",
    fuel: "DIESEL", gearbox: "AT", number_of_gears: "8",
    odriv_milestone: "QG6", area: "EUROPE", version: "4.6",
    target_vehicle: "P8 MHEV MDL2", eval_mode: "Full",
    // drive mode (AUTO/ECO/...) drives target selection; priority is fixed
    // to PREMIUM in the ODRIV tool (not user-selectable)
    mode: "AUTO", priority: "PREMIUM", gears: "AT",
  });
  const [saving, setSaving] = useState(false);
  const [savingMsg, setSavingMsg] = useState("");
  const [targetGroups, setTargetGroups] = useState(null);   // {references, tool, accdb}
  const [targetsLoading, setTargetsLoading] = useState(true);
  // milestone map: software-milestone name -> ODRIV milestone number (from CONFIGURATIONS)
  const milestoneMap = lists?.milestones || { MDL2: 4 };

  useEffect(() => {
    let cancelled = false;
    setTargetsLoading(true);
    // reading the shared .accdb can take a while over a network drive — give it
    // a generous timeout so the saved-project targets actually arrive.
    api.get("/targets/available", { timeout: 120000 })
      .then((r) => { if (!cancelled) { setTargetGroups(r.data); setTargetsLoading(false); } })
      .catch(() => { if (!cancelled) { setTargetGroups({ references: [], tool: [], accdb: [] }); setTargetsLoading(false); } });
    return () => { cancelled = true; };
  }, []);
  const odrivNumber = (name) => {
    const n = Number(milestoneMap[name]);
    return Number.isFinite(n) ? n : 4;
  };
  const set = (k) => (e) => {
    const v = e.target.value;
    // Gearbox type feeds the engine's "gears" gating field
    if (k === "gearbox") setForm({ ...form, gearbox: v, gears: v });
    // Software Milestone auto-resolves ODRIV Milestone via the milestone map
    // (selecting QG6 sets ODRIV milestone = 4). ODRIV milestone is a
    // derived number, not an independent choice.
    else if (k === "software_milestone") setForm({ ...form, software_milestone: v, odriv_milestone: v });
    else setForm({ ...form, [k]: v });
  };
  const milestones = Object.keys(lists?.milestones || { MDL2: 4 });
  const areas = lists?.areas || ["EUROPE", "CHINA", "North America", "LATAM", "India", "World"];
  const targets = lists?.target_vehicles || ["P8 MHEV MDL2", "24M_3.6_JL_PS-A_V222_0223", "24MY_JL_2.0T_VP_V150_091322"];
  const create = async () => {
    if (!form.name_code.trim() || !form.droopy.trim()) return;
    setSaving(true);
    setSavingMsg("Creating project…");
    try {
      await api.post("/project/new", form);
      // Only RECORD the selected target vehicle(s) — do not read or score them.
      // Scoring of targets happens later, when the user presses "Set as target"
      // on the RATING tab. So New Project closes instantly.
      const chosen = [...(form._targets || [])];
      if (chosen.length) {
        try {
          await api.post("/targets/pending", { primary: null, extras: chosen });
        } catch (e) { /* non-fatal: project still created */ }
      } else {
        // no targets selected -> clear any previous pending/target data
        try { await api.post("/targets/pending", { primary: null, extras: [] }); }
        catch (e) {}
      }
      onCreated();
    } finally { setSaving(false); setSavingMsg(""); }
  };
  // toggle a target vehicle in the multi-select (reference, tool, or accdb)
  const toggleTarget = (source, id, label) => {
    const cur = form._targets || [];
    const key = `${source}::${id ?? label}`;
    const exists = cur.some((c) => `${c.source}::${c.id ?? c.label}` === key);
    const next = exists
      ? cur.filter((c) => `${c.source}::${c.id ?? c.label}` !== key)
      : [...cur, { source, id, label }];
    setForm({ ...form, _targets: next });
  };
  const isTarget = (source, id, label) =>
    (form._targets || []).some((c) => c.source === source &&
      String(c.id ?? c.label) === String(id ?? label));
  const Sel = ({ k, opts }) => (
    <select value={form[k]} onChange={set(k)} data-testid={`np-${k}`}>
      {opts.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
  return (
    <Modal
      title="Start a new project…" onClose={onClose}
      footer={
        <>
          {saving && savingMsg && (
            <span style={{ fontSize: 11, color: "#0563C1", marginRight: "auto", maxWidth: 460 }} data-testid="np-saving-msg">
              {savingMsg}
            </span>
          )}
          <button className="xl-btn" onClick={onClose} data-testid="np-cancel">Cancel</button>
          <button className="xl-btn primary" onClick={create} disabled={saving || !form.name_code.trim() || !form.droopy.trim()} data-testid="np-create">
            {saving ? "Applying…" : "Apply"}
          </button>
        </>
      }
    >
      <div style={{ fontSize: 11.5, color: "#a33", marginBottom: 10 }}>
        Creating a new project erases all existing data (Erase_All2).
      </div>
      <div className="form-row"><label>Name / Code</label>
        <input value={form.name_code} onChange={set("name_code")} autoFocus data-testid="np-name_code" placeholder="K0_2.2 diesel_AT8" /></div>
      <div className="form-row"><label>Droopy line</label>
        <input value={form.droopy} onChange={set("droopy")} data-testid="np-droopy" /></div>
      <div className="form-row"><label>Software Milestone</label><Sel k="software_milestone" opts={milestones} /></div>
      <div className="form-row"><label>Engine type</label><Sel k="fuel" opts={["GASOLINE", "DIESEL"]} /></div>
      <div className="form-row"><label>Gearbox type</label><Sel k="gearbox" opts={["AT", "MT", "DCT", "CVT", "MANUAL GEARBOX"]} /></div>
      <div className="form-row"><label>Number Of Gears</label><Sel k="number_of_gears" opts={["5", "6", "7", "8", "9", "10"]} /></div>
      <div className="form-row"><label>ODRIV Milestone</label>
        <input value={odrivNumber(form.software_milestone)} readOnly disabled
          title="Auto-derived from Software Milestone (CONFIGURATIONS milestone map)"
          data-testid="np-odriv_milestone"
          style={{ background: "#eef2f7", color: "#555", fontWeight: 700 }} />
      </div>
      <div className="form-row"><label>Area</label><Sel k="area" opts={areas} /></div>
      <div className="form-row"><label>Version</label><Sel k="version" opts={["4.2", "4.6"]} /></div>
      <div className="form-row" style={{ alignItems: "flex-start" }}>
        <label style={{ paddingTop: 4 }}>Target vehicle(s)<br />
          <span style={{ fontWeight: 400, fontSize: 10, color: "#888" }}>(select one or more)</span></label>
        <div data-testid="np-targets" style={{ flex: 1, maxHeight: 190, overflow: "auto", border: "1px solid #d6d6d6", borderRadius: 3, padding: "4px 8px", background: "#fafbfc" }}>
          {(form._targets || []).length > 0 && (
            <div style={{ fontSize: 10.5, color: "#070", marginBottom: 4 }}>
              {form._targets.length} target{form._targets.length > 1 ? "s" : ""} selected
            </div>
          )}
          <div style={{ fontSize: 10, color: "#999", margin: "2px 0 1px" }}>REFERENCE VEHICLES</div>
          {(targetGroups?.references && targetGroups.references.length ? targetGroups.references : targets).map((o) => (
            <label key={`t-ref-${o}`} style={{ display: "flex", gap: 6, fontWeight: 400, fontSize: 11.5, padding: "1px 0" }}>
              <input type="checkbox" checked={isTarget("ref", null, o)}
                onChange={() => toggleTarget("ref", null, o)}
                data-testid={`np-target-ref`} />
              {o}
            </label>
          ))}
          {targetGroups?.tool?.length > 0 && (
            <div style={{ fontSize: 10, color: "#999", margin: "5px 0 1px" }}>SAVED PROJECTS — TOOL DATABASE</div>
          )}
          {(targetGroups?.tool || []).map((p) => (
            <label key={`t-tool-${p.id}`} style={{ display: "flex", gap: 6, fontWeight: 400, fontSize: 11.5, padding: "1px 0" }}>
              <input type="checkbox" checked={isTarget("tool", p.id, p.label)}
                onChange={() => toggleTarget("tool", p.id, p.label)}
                data-testid={`np-target-tool-${String(p.id).slice(0, 8)}`} />
              {p.label}{p.driv_index != null ? ` (driv ${p.driv_index})` : ""}
            </label>
          ))}
          {targetGroups?.accdb?.length > 0 && (
            <div style={{ fontSize: 10, color: "#999", margin: "5px 0 1px" }}>DATABASE VEHICLES — SHARED ACCESS DB</div>
          )}
          {(targetGroups?.accdb || []).map((p) => (
            <label key={`t-acc-${p.id}`} style={{ display: "flex", gap: 6, fontWeight: 400, fontSize: 11.5, padding: "1px 0" }}>
              <input type="checkbox" checked={isTarget("accdb", p.id, p.label)}
                onChange={() => toggleTarget("accdb", p.id, p.label)}
                data-testid={`np-target-accdb-${p.id}`} />
              {p.label} (ID {p.id})
            </label>
          ))}
        </div>
      </div>
      {targetsLoading && (
        <div className="form-row"><label></label>
          <span style={{ fontSize: 11, color: "#0563C1" }} data-testid="np-targets-loading">
            ⏳ Loading vehicles from the database… (reading the shared Access DB may take a moment)
          </span>
        </div>
      )}
      {!targetsLoading && targetGroups && (targetGroups.accdb?.length || 0) === 0 && (targetGroups.tool?.length || 0) === 0 && targetGroups.accdb_error && (
        <div className="form-row"><label></label>
          <span style={{ fontSize: 11, color: "#a00" }} data-testid="np-targets-empty">
            ⚠ {targetGroups.accdb_error}
          </span>
        </div>
      )}
      <div className="form-row"><label></label>
        <span style={{ fontSize: 10.5, color: "#888" }}>
          Targets are only recorded now. Calculate scores the current vehicle; press
          “Set as target” on the RATING tab to score the selected target(s).
        </span>
      </div>
      <div className="form-row"><label>Evaluation</label>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }} data-testid="np-eval_mode">
          <label style={{ display: "flex", gap: 5, fontWeight: 400 }}>
            <input type="radio" name="evalmode" checked={form.eval_mode === "Partiel"} onChange={() => setForm({ ...form, eval_mode: "Partiel" })} /> Partiel
          </label>
          <label style={{ display: "flex", gap: 5, fontWeight: 400 }}>
            <input type="radio" name="evalmode" checked={form.eval_mode === "Full"} onChange={() => setForm({ ...form, eval_mode: "Full" })} /> Full
          </label>
        </div>
      </div>
    </Modal>
  );
}

/* ---------------- DocVersions -> report ---------------- */
export function DocVersionsModal({ onClose }) {
  const [versions, setVersions] = useState(["", "", "", ""]);
  const [generating, setGenerating] = useState(null);
  const labels = ["Document version", "AVLD version", "Software version", "Calibration version"];
  const gen = async (fmtType) => {
    setGenerating(fmtType);
    try {
      const res = await api.post(`/report/${fmtType}`, { doc_versions: versions }, { responseType: "blob" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([res.data]));
      a.download = `ODRIV_report.${fmtType}`;
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e) {
      alert("Report failed: " + (e.response?.status === 400 ? "calculate the rating first" : e.message));
    } finally { setGenerating(null); }
  };
  return (
    <Modal
      title="DocVersions — CREATE REPORT" onClose={onClose}
      footer={
        <>
          <button className="xl-btn" onClick={onClose} data-testid="docv-cancel">Cancel</button>
          <button className="xl-btn primary" onClick={() => gen("pptx")} disabled={!!generating} data-testid="docv-pptx">
            {generating === "pptx" ? "Generating…" : "OK, suite → PowerPoint (.pptx)"}
          </button>
          <button className="xl-btn primary" onClick={() => gen("pdf")} disabled={!!generating} data-testid="docv-pdf">
            {generating === "pdf" ? "Generating…" : "PDF report"}
          </button>
        </>
      }
    >
      <div style={{ fontSize: 11.5, color: "#555", marginBottom: 10 }}>
        Enter the document version numbers (DocVersions D7:D10), then continue to the report engine.
      </div>
      {labels.map((l, i) => (
        <div className="form-row" key={l}>
          <label>{l}</label>
          <input value={versions[i]} data-testid={`docv-field-${i}`}
            onChange={(e) => setVersions(versions.map((v, j) => (j === i ? e.target.value : v)))} />
        </div>
      ))}
    </Modal>
  );
}

/* ---------------- OPEN DATABASE (form.frm) ---------------- */
export function OpenDatabaseModal({ onClose }) {
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [sdv, setSdv] = useState("");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const limit = 25;

  const load = async (s = skip) => {
    const res = await api.get("/events", { params: { skip: s, limit, sdv: sdv || undefined, search: search || undefined } });
    setEvents(res.data.events);
    setTotal(res.data.total);
  };
  useEffect(() => { load(0); setSkip(0); /* eslint-disable-next-line */ }, [sdv]);

  const del = async (id) => {
    if (!window.confirm("Delete this record from the database?")) return;
    await api.delete(`/events/${id}`);
    load();
  };

  return (
    <Modal title="OPEN DATABASE — _OdrivDB (events)" onClose={onClose} wide>
      <div className="cfg-toolbar">
        <input placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(0)} data-testid="db-search" style={{ width: 200 }} />
        <input placeholder="Filter by SDV…" value={sdv} onChange={(e) => setSdv(e.target.value)}
          data-testid="db-sdv-filter" style={{ width: 220 }} />
        <button className="xl-btn" onClick={() => load(0)} data-testid="db-refresh">Refresh</button>
        <span style={{ fontSize: 11.5, color: "#666" }}>{total} records</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          <button className="xl-btn" disabled={skip === 0} data-testid="db-prev"
            onClick={() => { const s = Math.max(0, skip - limit); setSkip(s); load(s); }}>◀</button>
          <button className="xl-btn" disabled={skip + limit >= total} data-testid="db-next"
            onClick={() => { const s = skip + limit; setSkip(s); load(s); }}>▶</button>
        </span>
      </div>
      <table className="xl-grid" style={{ width: "100%" }}>
        <thead>
          <tr><th>DB ID</th><th>SDV</th><th>Sub Event</th><th>File</th><th>Driv</th><th>Dyn</th><th></th></tr>
        </thead>
        <tbody>
          {events.map((ev) => (
            <tr key={ev.id} data-testid={`db-row-${ev.id.slice(0, 8)}`}>
              <td style={{ fontFamily: "monospace", fontSize: 11 }}>{ev.id.slice(0, 8)}</td>
              <td>{ev.sdv || <i style={{ color: "#999" }}>unclassified</i>}</td>
              <td>{String(findChan(ev.channels, "Sub Event Name") ?? "")}</td>
              <td style={{ fontSize: 11 }}>{ev.file}</td>
              <td style={{ color: dotColor(ev.driv) }}>{ev.driv ? `${fmt(ev.driv.indice, 2)} P${ev.driv.priority}` : "-"}</td>
              <td style={{ color: dotColor(ev.dyn) }}>{ev.dyn ? `${fmt(ev.dyn.indice, 2)} P${ev.dyn.priority}` : "-"}</td>
              <td>
                <button className="xl-btn" style={{ padding: "1px 7px" }} onClick={() => setEditing(ev)} data-testid={`db-edit-${ev.id.slice(0, 8)}`}>Edit</button>{" "}
                <button className="xl-btn" style={{ padding: "1px 7px" }} onClick={() => del(ev.id)} data-testid={`db-del-${ev.id.slice(0, 8)}`}>Del</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <EventEditModal event={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </Modal>
  );
}

function dotColor(part) {
  if (!part) return "#999";
  return { RED: "#c00", YELLOW: "#b8860b", GREEN: "#070" }[part.color] || "#333";
}

const VERDICT_BG = { "Low Risk": "#C6EFCE", "Medium Risk": "#FFEB9C", "High Risk": "#FBC7C7" };

export function SavedProjectsModal({ onClose, onLoaded }) {
  const [projects, setProjects] = useState([]);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("internal");      // internal | accdb
  const [accdbPath, setAccdbPath] = useState("");
  const [accdbProjects, setAccdbProjects] = useState([]);
  const [accdbStatus, setAccdbStatus] = useState(null);

  const load = async () => {
    try {
      const res = await api.get("/db/projects");
      setProjects(res.data.projects || []);
    } catch (e) { setErr(e.response?.data?.detail || e.message); }
  };
  useEffect(() => { load(); api.get("/accdb/status").then(r => setAccdbStatus(r.data)).catch(() => {});
    api.get("/settings").then(r => { if (r.data.accdb_path) setAccdbPath(r.data.accdb_path); }).catch(() => {}); }, []);

  const open = async (p) => {
    if (!window.confirm(`Load project "${p.code}" from the database?\nThis replaces the current active project.`)) return;
    setBusy(p.id);
    try { await api.post(`/db/projects/${p.id}/load`); onLoaded && onLoaded(); onClose(); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusy(null); }
  };

  const del = async (p) => {
    if (!window.confirm(`Delete saved project "${p.code}" from the database? This cannot be undone.`)) return;
    setBusy(p.id);
    try { await api.delete(`/db/projects/${p.id}`); await load(); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusy(null); }
  };

  // ---- shared Access .accdb (the calibration results database) ----
  const browseAccdb = async () => {
    if (!accdbPath) return;
    setBusy("accdb-list"); setErr(null);
    try {
      const res = await api.post("/accdb/projects", { path: accdbPath });
      setAccdbProjects(res.data.projects || []);
    } catch (e) { setErr(e.response?.data?.detail || e.message); setAccdbProjects([]); }
    finally { setBusy(null); }
  };

  const importAccdb = async (p) => {
    if (!window.confirm(`Import "${p.code}" (ID ${p.ID}) from the Access database into the tool?\nThis replaces the current active project.`)) return;
    setBusy(`acc-${p.ID}`);
    try {
      const res = await api.post("/accdb/import", { path: accdbPath, project_id: p.ID });
      alert(`Imported "${res.data.project.name_code}" with ${res.data.event_count} events. Calculate the rating to score it.`);
      onLoaded && onLoaded(); onClose();
    } catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusy(null); }
  };

  const exportAccdb = async () => {
    if (!accdbPath) { alert("Enter the path to the .accdb file first."); return; }
    if (!window.confirm(`Write the CURRENT processed project into:\n${accdbPath}\n\n(The project must be calculated first.)`)) return;
    setBusy("accdb-export");
    try {
      const res = await api.post("/accdb/export", { path: accdbPath });
      alert(`Project written to the Access database as ID ${res.data.project_id} (${res.data.event_count} events).`);
      await browseAccdb();
    } catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusy(null); }
  };

  return (
    <Modal title="DATABASE — Saved Projects" onClose={onClose} wide>
      <div style={{ display: "flex", gap: 6, marginBottom: 10, borderBottom: "1px solid #ddd" }}>
        <button className={`xl-btn${tab === "internal" ? " primary" : ""}`} onClick={() => setTab("internal")} data-testid="db-tab-internal">Tool database</button>
        <button className={`xl-btn${tab === "accdb" ? " primary" : ""}`} onClick={() => setTab("accdb")} data-testid="db-tab-accdb">Shared Access DB (.accdb)</button>
      </div>
      {err && <div style={{ color: "#a00", marginBottom: 8 }}>{err}</div>}

      {tab === "internal" && (<>
        <div style={{ fontSize: 11.5, color: "#666", marginBottom: 8 }}>
          Projects saved inside this tool. Open one to restore its events and scorecard.
          Save new projects from the RATING sheet after calculating.
        </div>
        <div style={{ maxHeight: 430, overflow: "auto" }}>
          <table className="xl-grid" style={{ width: "100%", fontSize: 11.5 }}>
            <thead><tr>
              <th>Date</th><th>Code</th><th>Energy</th><th>Gears</th><th>Mode</th>
              <th>Ver.</th><th>Target vehicle</th><th>Driv</th><th>Resp</th><th>Events</th><th>SDVs</th><th></th>
            </tr></thead>
            <tbody>
              {projects.length === 0 && (
                <tr><td colSpan={12} style={{ textAlign: "center", color: "#999", padding: 14 }}>
                  No saved projects yet. Process a project and click “SAVE TO DATABASE” on the RATING sheet.
                </td></tr>)}
              {projects.map((p) => (
                <tr key={p.id} data-testid={`saved-proj-${p.id.slice(0, 8)}`}>
                  <td style={{ whiteSpace: "nowrap" }}>{(p.DateCreation || "").slice(0, 16).replace("T", " ")}</td>
                  <td style={{ fontWeight: 600 }}>{p.code}</td>
                  <td>{p.energy}</td><td>{p.gears}{p.NbGear ? ` / ${p.NbGear}` : ""}</td>
                  <td>{p.Mode}</td><td>{p.Version}</td>
                  <td style={{ fontSize: 11 }}>{p.target_vehicle}</td>
                  <td style={{ background: VERDICT_BG[p.driv_verdict] || "transparent", textAlign: "center" }}>{p.driv_index != null ? fmt(p.driv_index, 1) : "-"}</td>
                  <td style={{ background: VERDICT_BG[p.dyn_verdict] || "transparent", textAlign: "center" }}>{p.dyn_index != null ? fmt(p.dyn_index, 1) : "-"}</td>
                  <td style={{ textAlign: "right" }}>{p.event_count ?? "-"}</td>
                  <td style={{ textAlign: "right" }}>{p.sdv_count ?? "-"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="xl-btn" style={{ padding: "1px 7px" }} disabled={busy === p.id} onClick={() => open(p)} data-testid={`saved-open-${p.id.slice(0, 8)}`}>Open</button>{" "}
                    <button className="xl-btn" style={{ padding: "1px 7px" }} disabled={busy === p.id} onClick={() => del(p)} data-testid={`saved-del-${p.id.slice(0, 8)}`}>Del</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>)}

      {tab === "accdb" && (<>
        <div style={{ fontSize: 11.5, color: "#666", marginBottom: 8 }}>
          Read and write the shared Access database file directly, so tools share one
          database. Enter the <b>folder</b> that holds the <code>_OdrivDB_*.accdb</code> files
          (the year subfolder), then browse to
          import a project, or export the current processed project into it.
          {accdbStatus && !accdbStatus.write_available && (
            <span style={{ color: "#a60" }}> &nbsp;(Writing needs a Java runtime on this machine; importing works without it.)</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <input placeholder="Y:\\TransTrqCal\\Shift Quality Validation\\Odriv DB\\db" value={accdbPath}
            onChange={(e) => setAccdbPath(e.target.value)} data-testid="accdb-path"
            style={{ flex: 1 }} onKeyDown={(e) => e.key === "Enter" && browseAccdb()} />
          <button className="xl-btn primary" onClick={browseAccdb} disabled={busy === "accdb-list" || !accdbPath} data-testid="accdb-browse">
            {busy === "accdb-list" ? "Reading…" : "Browse"}
          </button>
          <button className="xl-btn" onClick={exportAccdb} disabled={busy === "accdb-export" || !accdbPath} data-testid="accdb-export"
            title="Write the current processed project into this .accdb">
            {busy === "accdb-export" ? "Writing…" : "⤓ Export current project here"}
          </button>
        </div>
        <div style={{ maxHeight: 400, overflow: "auto" }}>
          <table className="xl-grid" style={{ width: "100%", fontSize: 11.5 }}>
            <thead><tr>
              <th>ID</th><th>Date</th><th>Code</th><th>Energy</th><th>Gears</th>
              <th>Mode</th><th>Ver.</th><th>Milestone</th><th>Target vehicle</th><th></th>
            </tr></thead>
            <tbody>
              {accdbProjects.length === 0 && (
                <tr><td colSpan={10} style={{ textAlign: "center", color: "#999", padding: 14 }}>
                  Enter a .accdb path and click Browse to list the projects inside it.
                </td></tr>)}
              {accdbProjects.map((p) => (
                <tr key={p.ID} data-testid={`accdb-proj-${p.ID}`}>
                  <td>{p.ID}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{(p.DateCreation || "").slice(0, 16).replace("T", " ")}</td>
                  <td style={{ fontWeight: 600 }}>{p.code}</td>
                  <td>{p.energy}</td><td>{p.gears}{p.NbGear ? ` / ${p.NbGear}` : ""}</td>
                  <td>{p.Mode}</td><td>{p.Version}</td><td style={{ textAlign: "center" }}>{p.milestone}</td>
                  <td style={{ fontSize: 11 }}>{p.target_vehicle}</td>
                  <td><button className="xl-btn" style={{ padding: "1px 7px" }} disabled={busy === `acc-${p.ID}`}
                    onClick={() => importAccdb(p)} data-testid={`accdb-import-${p.ID}`}>Import</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>)}
    </Modal>
  );
}

function findChan(channels, name) {
  for (const [k, v] of Object.entries(channels || {})) {
    if (k.toLowerCase().includes(name.toLowerCase())) return v;
  }
  return null;
}

function EventEditModal({ event, onClose, onSaved }) {
  const [channels, setChannels] = useState({ ...event.channels });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/events/${event.id}`, { channels });
      onSaved();
    } finally { setSaving(false); }
  };
  return (
    <Modal title={`Edit record ${event.id.slice(0, 8)} — ${event.sdv}`} onClose={onClose} wide
      footer={
        <>
          <button className="xl-btn" onClick={onClose}>Cancel</button>
          <button className="xl-btn primary" onClick={save} disabled={saving} data-testid="event-save">
            {saving ? "Saving…" : "Save record"}
          </button>
        </>
      }>
      <div style={{ maxHeight: 420, overflow: "auto" }}>
        <table className="xl-grid" style={{ width: "100%" }}>
          <thead><tr><th style={{ width: "55%" }}>Channel (Family, Channel)</th><th>Value</th></tr></thead>
          <tbody>
            {Object.entries(channels).map(([k, v]) => (
              <tr key={k}>
                <td style={{ fontSize: 11 }}>{k.replace(/\u00b7/g, ".")}</td>
                <td>
                  <input className="xl-cell-input" value={String(v ?? "")} data-testid={`chan-${k.slice(0, 12)}`}
                    onChange={(e) => setChannels({ ...channels, [k]: e.target.value })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
