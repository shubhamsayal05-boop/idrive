import React from "react";

/**
 * Catches render-time exceptions anywhere in the tree so a single bad component
 * shows a readable error instead of blanking the whole page (white screen).
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // surface to the console for debugging
    // eslint-disable-next-line no-console
    console.error("ODRIV render error:", error, info);
    this.setState({ info });
  }

  render() {
    if (this.state.error) {
      const msg = this.state.error?.message || String(this.state.error);
      const stack = this.state.info?.componentStack || "";
      return (
        <div style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
          <div style={{ background: "#fdecea", border: "1px solid #f5c6cb",
            borderRadius: 6, padding: "14px 18px", maxWidth: 900 }}>
            <div style={{ fontWeight: 700, color: "#a12", fontSize: 15, marginBottom: 6 }}>
              Something went wrong rendering this view.
            </div>
            <div style={{ fontSize: 13, color: "#333", marginBottom: 10 }}>
              {msg}
            </div>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <button onClick={() => { window.location.hash = "HOME"; window.location.reload(); }}
                style={{ padding: "6px 12px", cursor: "pointer" }}>
                Go to HOME &amp; reload
              </button>
              <button onClick={() => this.setState({ error: null, info: null })}
                style={{ padding: "6px 12px", cursor: "pointer" }}>
                Try again
              </button>
            </div>
            {stack ? (
              <details style={{ fontSize: 11, color: "#666" }}>
                <summary style={{ cursor: "pointer" }}>Technical details</summary>
                <pre style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{stack}</pre>
              </details>
            ) : null}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
