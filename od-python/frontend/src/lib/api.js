import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const fmt = (v, nd = 1) => {
  if (v === null || v === undefined || v === "") return "-";
  const f = Number(v);
  if (Number.isNaN(f)) return String(v);
  return f.toFixed(nd);
};

export const DOT_COLORS = {
  RED: "#FF0000",
  YELLOW: "#FFC000",
  ORANGE: "#FFC000",
  GREEN: "#00B050",
  NONE: "#BFBFBF",
};

export const VERDICT_COLORS = {
  "Low Risk": "#00B050",
  "Medium Risk": "#FFC000",
  "High Risk": "#FF0000",
};

export const CELL_COLORS = {
  RED: "#FF0000",
  YELLOW: "#FFFF00",
  GREEN: "#00B050",
};

export function getChannel(channels, name) {
  if (!channels) return null;
  if (channels[name] !== undefined) return channels[name];
  const ln = String(name).replace(/\u00b7/g, ".").trim().toLowerCase();
  for (const [k, v] of Object.entries(channels)) {
    const kk = String(k).replace(/\u00b7/g, ".").trim().toLowerCase();
    if (kk === ln) return v;
    if (kk.includes(",") && kk.split(",").slice(1).join(",").trim() === ln) return v;
  }
  if (ln.includes(",")) {
    const part = ln.split(",").slice(1).join(",").trim();
    for (const [k, v] of Object.entries(channels)) {
      const kk = String(k).replace(/\u00b7/g, ".").trim().toLowerCase();
      if (kk === part) return v;
      if (kk.includes(",") && kk.split(",").slice(1).join(",").trim() === part) return v;
    }
  }
  return null;
}

export async function downloadBlob(url, body, filename) {
  const res = await api.post(url, body, { responseType: "blob" });
  const blob = new Blob([res.data]);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}
