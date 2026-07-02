import { useRef, useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useWorkbook } from "@/components/Workbook";
import { NewProjectModal, DocVersionsModal, OpenDatabaseModal, SavedProjectsModal } from "@/components/modals";

const NAVY = "#1E2336";
const SLATE = "#556F81";

const FIELDS = [
  ["MODE", "mode", ["AUTO", "ECO", "SPORT", "MANUAL", "Hybrid", "ZEV", "eSAVE"]],
  ["FUEL", "fuel", ["GASOLINE", "DIESEL"]],
  ["GEARS", "gears", ["5", "6", "7", "8", "9", "10"]],
  ["SOFTWARE MILESTONE", "software_milestone", null],
  ["PRIORITY", "priority", ["PREMIUM", "MAINSTREAM"]],
  ["VERSION", "version", ["4.2", "4.6"]],
  ["ODRIV MILESTONE", "odriv_milestone", null],
  ["AREA", "area", null],
  ["TARGET VEHICLE", "target_vehicle", "text"],
  ["NUMBER OF GEARS", "number_of_gears", ["5", "6", "7", "8", "9", "10"]],
];

export default function HomeSheet() {
  const { state, refresh, openTab, setSelection } = useWorkbook();
  const project = state?.project;
  const [modal, setModal] = useState(null);
  const [busyMsg, setBusyMsg] = useState(null);
  const [lists, setLists] = useState(null);
  const [accdbPath, setAccdbPath] = useState("");
  const [accdbYear, setAccdbYear] = useState("");
  const [accdbSaved, setAccdbSaved] = useState(false);
  const [accdbInfo, setAccdbInfo] = useState(null);
  const [calcProgress, setCalcProgress] = useState(null); // {percent, phase} while running
  const fileRef = useRef(null);
  const lastLog = state?.log_tail?.[0]?.message || "";

  useEffect(() => {
    api.get("/settings").then((r) => {
      const p = r.data.accdb_path || "";
      const y = r.data.accdb_year || "";
      setAccdbPath(p); setAccdbYear(y);
      if (p) checkAccdbPath(p, y);
    }).catch(() => {});
  }, []);

  const checkAccdbPath = async (p, y) => {
    try {
      const r = await api.post("/accdb/check-path",
        { path: p ?? accdbPath, year: y ?? accdbYear });
      setAccdbInfo(r.data);
    } catch { setAccdbInfo(null); }
  };

  const saveAccdbPath = async () => {
    try {
      await api.put("/settings", { accdb_path: accdbPath, accdb_year: accdbYear });
      setAccdbSaved(true);
      await checkAccdbPath(accdbPath, accdbYear);
      setTimeout(() => setAccdbSaved(false), 2000);
    } catch (e) { alert(e.response?.data?.detail || e.message); }
  };

  const ensureLists = async () => {
    if (lists) return lists;
    const res = await api.get("/config/configurations");
    setLists(res.data);
    return res.data;
  };

  const run = async (label, fn) => {
    setBusyMsg(label);
    try { await fn(); await refresh(); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setBusyMsg(null); }
  };

  const onField = (key) => async (e) => {
    const v = e.target.value;
    // Software Milestone change auto-updates ODRIV Milestone via the milestone
    // map (QG6 -> ODRIV milestone 4). Send both together.
    if (key === "software_milestone") {
      await run("Updating project…", () => api.put("/project", { software_milestone: v, odriv_milestone: v }));
    } else {
      await run("Updating project…", () => api.put("/project", { [key]: v }));
    }
  };
  const milestoneNum = (name) => {
    const n = Number((lists?.milestones || {})[name]);
    return Number.isFinite(n) ? n : "";
  };

  const addFile = () => {
    if (!project) return alert("Project information missing. Use NEW PROJECT first.");
    fileRef.current?.click();
  };

  const onFilePicked = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    await run("LoadData : importing acquisition file…", async () => {
      const res = await api.post("/import/file", fd);
      const d = res.data;
      alert(`File added to your project.\nImported: ${d.imported}\nClassified: ${d.classified}\nUnclassified: ${d.unclassified}\nSDV sheets: ${Object.keys(d.per_sdv).length}`);
    });
  };

  const demo = () =>
    run("Generating demo acquisition…", async () => {
      const res = await api.post("/import/demo");
      const d = res.data;
      alert(`Demo acquisition added.\nImported: ${d.imported} events across ${Object.keys(d.per_sdv).length} SDV sheets.`);
    });

  const calculate = async () => {
    try {
      setCalcProgress({ percent: 0, phase: "Starting…" });
      await api.post("/rating/calculate/start", null, { timeout: 30000 });
      // poll progress until done; creep the bar slightly between server updates
      // so a long per-vehicle read doesn't look frozen.
      let done = false, guard = 0, lastServer = 0, shown = 0;
      while (!done && guard < 100000) {
        guard++;
        await new Promise((r) => setTimeout(r, 400));
        let p;
        try { p = (await api.get("/rating/progress", { timeout: 30000 })).data; }
        catch { continue; }
        const server = p.percent || 0;
        if (server > lastServer) { lastServer = server; shown = server; }
        else {
          // creep up to 2 points toward the next server milestone, capped
          shown = Math.min(shown + 1, Math.min(98, lastServer + 8));
        }
        setCalcProgress({ percent: Math.max(shown, server), phase: p.phase || "",
          read_method: p.read_method, read_detail: p.read_detail });
        if (p.done) {
          done = true;
          if (p.error) {
            setCalcProgress(null);
            alert("Calculation error: " + p.error);
            return;
          }
        }
      }
      setCalcProgress({ percent: 100, phase: "Done" });
      await new Promise((r) => setTimeout(r, 250));
      setCalcProgress(null);
      await refresh();
      openTab("RATING");
    } catch (e) {
      setCalcProgress(null);
      alert(e.response?.data?.detail || e.message);
    }
  };

  const eraseAll = () => {
    if (!project) return alert("No project to erase.");
    if (!window.confirm("This operation will delete all your data. Continue?")) return;
    run("Erase_All2…", () => api.delete("/project"));
  };

  const cellSel = (addr, value) => () => setSelection({ addr, value });

  return (
    <div style={{ minHeight: "100%", background: "#fff" }}>
      {/* row 1 banner */}
      <div style={{ background: NAVY, color: "#fff", padding: "14px 30px", display: "flex", alignItems: "baseline", gap: 30 }}>
        <span style={{ fontSize: 34, fontWeight: 700, letterSpacing: 6 }} data-testid="home-title">ODRIV</span>
      </div>

      <div style={{ display: "flex", gap: 26, padding: "20px 30px", flexWrap: "wrap" }}>
        {/* PROJECT SETTINGS panel */}
        <div style={{ background: SLATE, padding: "12px 16px 18px", minWidth: 480, color: "#fff" }}>
          <div style={{ fontWeight: 700, fontSize: 14, letterSpacing: 1, marginBottom: 10 }}>PROJECT SETTINGS</div>

          <Label text="ID" />
          <Cell value={project?.id?.slice(0, 13) || ""} readOnly testid="home-id" onClick={cellSel("C7", project?.id || "")} />

          <Label text="NAME / CODE" />
          <Cell value={project?.name_code || ""} readOnly testid="home-name_code"
            onClick={cellSel("C9", project?.name_code || "")} wide />

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 18 }}>
            {FIELDS.map(([label, key, opts]) => (
              <div key={key}>
                <Label text={label} />
                {project ? (
                  key === "odriv_milestone" ? (
                    <input
                      value={milestoneNum(project.software_milestone)} readOnly disabled
                      data-testid={`home-field-${key}`}
                      title="Auto-derived from Software Milestone (CONFIGURATIONS milestone map)"
                      style={{ ...inputStyle, background: "#eef2f7", color: "#555", fontWeight: 700 }}
                    />
                  ) : opts === "text" ? (
                    <input
                      defaultValue={project[key] || ""} onBlur={onField(key)}
                      data-testid={`home-field-${key}`}
                      style={inputStyle} onFocus={cellSel(label, project[key] || "")}
                    />
                  ) : (
                    <select
                      value={project[key] || ""} onChange={onField(key)}
                      data-testid={`home-field-${key}`} style={inputStyle}
                      onFocus={cellSel(label, project[key] || "")}
                    >
                      <option value="">—</option>
                      {(opts || dynamicOpts(key, lists)).map((o) => (
                        <option key={o} value={o}>{o}</option>
                      ))}
                    </select>
                  )
                ) : (
                  <Cell value="" readOnly testid={`home-field-${key}`} />
                )}
              </div>
            ))}
          </div>
          {!project && (
            <div style={{ marginTop: 12, fontSize: 12, background: "#FFFFFFAA", color: "#333", padding: "6px 8px" }}>
              No project. Click <b>NEW PROJECT</b> to start.
            </div>
          )}
        </div>

        {/* button stack */}
        <div style={{ display: "flex", flexDirection: "column", gap: 7, minWidth: 240 }}>
          <button className="xl-btn primary" data-testid="btn-new-project"
            onClick={async () => { await ensureLists(); setModal("new"); }}>NEW PROJECT</button>
          <button className="xl-btn" data-testid="btn-add-file" onClick={addFile}>ADD FILE TO DATABASE</button>
          <button className="xl-btn" data-testid="btn-add-subjective" disabled title="Empty stub in v29.2.1 AT">ADD FILE (SUBJECTIVE)</button>
          <button className="xl-btn" data-testid="btn-open-database" onClick={() => setModal("db")}>OPEN DATABASE</button>
          <button className="xl-btn" data-testid="btn-saved-projects" onClick={() => setModal("saved")}>📁 SAVED PROJECTS</button>
          <button className="xl-btn primary" data-testid="btn-calculate-rating" onClick={calculate}
            disabled={!state?.total_events}>CALCULATE RATING</button>
          <button className="xl-btn" data-testid="btn-create-report" onClick={() => setModal("report")}
            disabled={!state?.has_rating}>CREATE REPORT</button>
          <button className="xl-btn danger" data-testid="btn-erase-all" onClick={eraseAll}>ERASE ALL DATA</button>
          <button className="xl-btn" data-testid="btn-versions" onClick={() => openTab("VERSIONS")}>VERSIONS</button>
          <div style={{ borderTop: "1px solid #ccc", margin: "6px 0" }} />
          <button className="xl-btn" data-testid="btn-demo-data" onClick={demo} disabled={!project}>
            ⚙ Generate demo acquisition
          </button>
          <a className="xl-btn" style={{ textAlign: "center", textDecoration: "none" }}
            href={`${api.defaults.baseURL}/import/sample`} data-testid="btn-download-sample">
            ⬇ Download sample TRIE file
          </a>
          <input ref={fileRef} type="file" accept=".xlsx,.xlsm" hidden onChange={onFilePicked}
            data-testid="file-input" />
        </div>

        {/* status panel */}
        <div style={{ minWidth: 280, flex: 1 }}>
          <table className="xl-grid" style={{ width: "100%" }}>
            <tbody>
              <tr><td className="rowhead">Events in DB</td><td className="num" data-testid="home-total-events">{state?.total_events ?? 0}</td></tr>
              <tr><td className="rowhead">SDV sheets generated</td><td className="num" data-testid="home-sheet-count">{state?.sheets?.length ?? 0}</td></tr>
              <tr><td className="rowhead">Rating calculated</td><td data-testid="home-has-rating">{state?.has_rating ? "Yes" : "No"}</td></tr>
            </tbody>
          </table>
          <div style={{ marginTop: 10, fontSize: 11, color: "#555" }}>Moniteur</div>
          <div className={`moniteur ${busyMsg ? "busy" : ""}`} data-testid="moniteur">
            {busyMsg ? <><span className="spin" /> {busyMsg}</> : lastLog || "Ready."}
          </div>

          <div style={{ marginTop: 14, padding: "8px 10px", border: "1px solid #d6d6d6", background: "#f7f9fb" }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: "#17375E", marginBottom: 4 }}>
              Shared database (Access)
            </div>
            <div style={{ fontSize: 11, color: "#777", marginBottom: 6 }}>
              The <b>folder</b> that holds <code>_OdrivDB.accdb</code> — the shared
              database path, e.g.
              <code> Y:\TransTrqCal\Shift Quality Validation\Odriv DB\db</code>. The event
              databases live in a <b>year</b> subfolder (e.g. 2024). The
              drive must be connected (VPN).
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <input value={accdbPath} onChange={(e) => setAccdbPath(e.target.value)}
                placeholder="Y:\TransTrqCal\Shift Quality Validation\Odriv DB\db"
                data-testid="home-accdb-path" style={{ flex: 1, fontSize: 11.5 }}
                onKeyDown={(e) => e.key === "Enter" && saveAccdbPath()} />
              <input value={accdbYear} onChange={(e) => setAccdbYear(e.target.value)}
                placeholder="Year" title="Year subfolder, e.g. 2024"
                data-testid="home-accdb-year" style={{ width: 70, fontSize: 11.5 }}
                onKeyDown={(e) => e.key === "Enter" && saveAccdbPath()} />
              <button className="xl-btn" onClick={saveAccdbPath} data-testid="home-accdb-save">
                {accdbSaved ? "✓ Saved" : "Save path"}
              </button>
            </div>
            {accdbInfo && (
              <div style={{ fontSize: 11, marginTop: 6, color: accdbInfo.ok ? "#070" : "#a00" }}
                data-testid="home-accdb-status">
                {accdbInfo.ok
                  ? `✓ Found ${accdbInfo.count} database file${accdbInfo.count > 1 ? "s" : ""}: ${accdbInfo.found.join(", ")}`
                  : "✗ No _OdrivDB.accdb found here. Check the path and that the VPN / mapped drive is connected."}
                {accdbInfo.year_folders && accdbInfo.year_folders.length > 0 && !accdbYear && (
                  <div style={{ color: "#a60", marginTop: 2 }}>
                    Year subfolders found: {accdbInfo.year_folders.join(", ")} — set the Year above
                    to load events from the right one.
                  </div>
                )}
              </div>
            )}
          </div>
          <div style={{ marginTop: 14, fontSize: 11.5, color: "#777", lineHeight: 1.6 }}>
            Workflow: NEW PROJECT → ADD FILE TO DATABASE (acquisition .xlsx with a <b>TRIE</b> tab)
            → CALCULATE RATING → review the RATING scorecard &amp; SDV sheets → CREATE REPORT.
          </div>
        </div>
      </div>

      {modal === "new" && (
        <NewProjectModal lists={lists} onClose={() => setModal(null)}
          onCreated={async () => { setModal(null); await refresh(); }} />
      )}
      {modal === "db" && <OpenDatabaseModal onClose={() => setModal(null)} />}
      {modal === "saved" && <SavedProjectsModal onClose={() => setModal(null)}
        onLoaded={async () => { await refresh(); }} />}
      {modal === "report" && <DocVersionsModal onClose={() => setModal(null)} />}

      {calcProgress && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9999 }}
          data-testid="calc-progress-overlay">
          <div style={{ background: "#fff", borderRadius: 8, padding: "26px 30px",
            width: 480, boxShadow: "0 12px 40px rgba(0,0,0,0.3)" }}>
            <div style={{ fontWeight: 700, fontSize: 15, color: "#1E2336", marginBottom: 4 }}>
              Calculating rating…
            </div>
            <div style={{ fontSize: 12, color: "#666", marginBottom: 16, minHeight: 32 }}
              data-testid="calc-progress-phase">
              {calcProgress.phase || "Working…"}
            </div>
            <div style={{ background: "#E6E8EE", borderRadius: 20, height: 22, overflow: "hidden", position: "relative" }}>
              <div style={{ width: `${calcProgress.percent}%`, height: "100%",
                background: "linear-gradient(90deg,#2E6FC5,#3F8AE0)", borderRadius: 20,
                transition: "width 0.3s ease" }}
                data-testid="calc-progress-bar" />
              <div style={{ position: "absolute", inset: 0, display: "flex",
                alignItems: "center", justifyContent: "center", fontSize: 12,
                fontWeight: 700, color: calcProgress.percent > 50 ? "#fff" : "#1E2336" }}
                data-testid="calc-progress-percent">
                {calcProgress.percent}%
              </div>
            </div>
            <div style={{ fontSize: 10.5, color: "#999", marginTop: 12, textAlign: "center", lineHeight: 1.5 }}>
              {calcProgress.read_method === "python" ? (
                <span style={{ color: "#a60" }}>
                  Reading the database in compatibility mode (slow on the first read of
                  each vehicle). After this, the same vehicle is cached and instant.
                </span>
              ) : calcProgress.read_method === "jdbc" ? (
                <span style={{ color: "#070" }}>Fast database read (JDBC).</span>
              ) : (
                "Comparison vehicles are read from the shared database here. The first read of a given vehicle can take a minute; it's cached afterwards."
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const inputStyle = {
  width: "100%", border: "1px solid #9AB", padding: "4px 6px", fontSize: 12.5,
  background: "#fff", color: "#222", marginBottom: 2, borderRadius: 0,
};

function dynamicOpts(key, lists) {
  if (!lists) return ["MDL2"];
  if (key.includes("milestone")) return Object.keys(lists.milestones || {});
  if (key === "area") return lists.areas || [];
  return [];
}

function Label({ text }) {
  return <div style={{ fontSize: 10.5, letterSpacing: 0.5, margin: "8px 0 2px", opacity: 0.85 }}>{text}</div>;
}

function Cell({ value, readOnly, testid, onClick, wide }) {
  return (
    <div onClick={onClick} data-testid={testid}
      style={{ ...inputStyle, minHeight: 24, cursor: "default", width: wide ? "100%" : undefined, background: readOnly ? "#EDF1F4" : "#fff" }}>
      {value}
    </div>
  );
}
