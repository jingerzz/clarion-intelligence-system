import { useState } from "react";

/*
 * SKIP EVALUATION ZO SPACE TEMPLATE
 * =====================================
 * USAGE: Replace all {{PLACEHOLDER}} values with ticker-specific data.
 * RULES:
 *   - NO unicode escape sequences (\u2019, \u201c, \u201d, \u2014, etc.).
 *     Use plain ASCII quotes/apostrophes/dashes only.
 *   - Keep the 4-section structure: Why I'm Passing, SEC Evidence,
 *     Valuation, Revisit Triggers.
 *   - Theme colors should reflect the company's visual identity.
 */

// ---- THEME (per-ticker customization) ----
const theme = {
  bg: "{{THEME_BG}}",
  card: "{{THEME_CARD}}",
  border: "{{THEME_BORDER}}",
  accent: "{{THEME_ACCENT}}",
  accentLight: "{{THEME_ACCENT_LIGHT}}",
  accentSoft: "{{THEME_ACCENT_SOFT}}",
  fg: "{{THEME_FG}}",
  muted: "{{THEME_MUTED}}",
  green: "#42BE65",
  red: "#FA4D56",
  yellow: "#F1C21B",
  kill: "#FA4D56",
};

// ---- LIVE DATA (must be fetched before writing) ----
const price = {{PRICE}};
const prevClose = {{PREV_CLOSE}};
const change = price - prevClose;
const changePct = prevClose !== 0 ? ((price - prevClose) / prevClose) * 100 : 0;
const timestamp = "{{TIMESTAMP}}";
const dataTs = "{{DATA_TS}}";

// ---- HELPERS ----
function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtB(n: number) { if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`; if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`; if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`; return fmt(n); }

// ---- TICKER STATS BAR (max ~12 items) ----
const tickerItems: [string, string][] = [
  {{TICKER_ITEMS}}
];

// ---- RED FLAGS (Why I'm Passing -- 3-5 items) ----
const redFlags: { label: string; body: string }[] = [
  {{RED_FLAGS}}
];

// ---- VALUATION SCENARIOS (Bear / Price-Would-Change-Mind / Bull) ----
const valuationScenarios: { label: string; price: string; updown: string; desc: string; color: string }[] = [
  {{VALUATION_SCENARIOS}}
];

// ---- REVISIT TRIGGERS (concrete conditions to flip to Add) ----
const revisitTriggers: string[] = [
  {{REVISIT_TRIGGERS}}
];

// ---- TEXT BLOCKS ----
const verdictSummary = "{{VERDICT_SUMMARY}}";
const sourcesEDGAR = "{{SOURCES_EDGAR}}";
const citationsShort = "{{CITATIONS_SHORT}}";

// ---- COMPONENT ----
export default function SkipEval() {
  const [tab, setTab] = useState("pass");

  const tabs: [string, string][] = [
    ["pass", "Why I'm Passing"],
    ["evidence", "SEC Evidence"],
    ["valuation", "Valuation"],
    ["revisit", "Revisit Triggers"],
  ];

  const tabStyle = (key: string) => ({
    padding: "10px 18px",
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: tab === key ? 700 : 400,
    color: tab === key ? theme.accent : theme.muted,
    borderBottom: tab === key ? `2px solid ${theme.accent}` : "2px solid transparent",
  } as React.CSSProperties);

  return (
    <div style={{ background: theme.bg, color: theme.fg, fontFamily: "'Inter', system-ui, sans-serif", minHeight: "100vh" }}>
      {/* NAV */}
      <div style={{ borderBottom: `1px solid ${theme.border}`, padding: "12px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(0,0,0,0.6)" }}>
        <span style={{ fontSize: 12, color: theme.muted, letterSpacing: "0.08em", textTransform: "uppercase" }}>Clarion Intelligence Systems</span>
        <span style={{ fontSize: 11, color: theme.muted }}>{{REGIME_LINE}}</span>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 20px" }}>
        {/* HEADER */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 20, marginBottom: 28 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
              <div style={{ width: 48, height: 48, borderRadius: 8, background: theme.accent, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: 18, fontWeight: 800, color: theme.bg }}>{{TICKER_SHORT}}</span>
              </div>
              <div>
                <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: "0.02em" }}>{{TICKER}}</div>
                <div style={{ fontSize: 13, color: theme.muted }}>{{COMPANY_NAME}}</div>
              </div>
            </div>
            <div style={{ fontSize: 12, color: theme.muted, background: theme.accentSoft, border: `1px solid ${theme.border}`, borderRadius: 6, padding: "4px 10px", display: "inline-block" }}>
              Skip Evaluation -- {{DATE}}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 42, fontWeight: 700, letterSpacing: "-0.03em" }}>${fmt(price)}</div>
            <div style={{ fontSize: 16, color: change >= 0 ? theme.green : theme.red, fontWeight: 600 }}>
              {change >= 0 ? "▲" : "▼"} ${Math.abs(change).toFixed(2)} ({Math.abs(changePct).toFixed(2)}%)
            </div>
            <div style={{ fontSize: 11, color: theme.muted, marginTop: 4 }}>Close {timestamp} -- via yfinance -- {dataTs}</div>
          </div>
        </div>

        {/* SKIP VERDICT */}
        <div style={{ background: "linear-gradient(135deg, rgba(250,77,86,0.13), rgba(250,77,86,0.03))", border: `1px solid ${theme.border}`, borderRadius: 12, padding: "18px 22px", marginBottom: 24 }}>
          <div style={{ fontSize: 11, color: theme.kill, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Verdict</div>
          <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.4 }}>{verdictSummary}</div>
        </div>

        {/* STATS BAR */}
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(tickerItems.length, 6)}, 1fr)`, gap: 10, marginBottom: 24 }}>
          {tickerItems.map(([label, value]) => (
            <div key={label} style={{ background: theme.card, border: `1px solid ${theme.border}`, borderRadius: 10, padding: "12px 10px", textAlign: "center" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: value.startsWith("-") ? theme.red : theme.accent }}>{value}</div>
              <div style={{ fontSize: 10, color: theme.muted, marginTop: 3, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
            </div>
          ))}
        </div>

        {/* TABS */}
        <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: `1px solid ${theme.border}` }}>
          {tabs.map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)} style={tabStyle(key)}>
              {label}
            </button>
          ))}
        </div>

        {/* CONTENT */}
        {tab === "pass" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ background: theme.card, border: `1px solid ${theme.border}`, borderRadius: 12, padding: 22 }}>
              <h2 style={{ fontSize: 22, fontWeight: 700, color: theme.fg, margin: "0 0 20px 0" }}>Why I'm Passing</h2>
              {{PASS_PARAGRAPHS}}
            </div>
            <div style={{ background: "rgba(250,77,86,0.06)", border: "1px solid rgba(250,77,86,0.2)", borderRadius: 12, padding: 22 }}>
              <div style={{ fontSize: 12, color: theme.kill, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 14 }}>Red Flags</div>
              {redFlags.map((rf, i) => (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12, padding: "12px 14px", background: "rgba(250,77,86,0.06)", borderRadius: 8, border: "1px solid rgba(250,77,86,0.12)" }}>
                  <span style={{ fontSize: 20, fontWeight: 800, color: i === 0 ? theme.red : theme.yellow }}>{i + 1}</span>
                  <div>
                    <div style={{ fontSize: 13, color: theme.fg, fontWeight: 600, marginBottom: 4 }}>{rf.label}</div>
                    <div style={{ fontSize: 12, color: theme.muted, lineHeight: 1.6 }}>{rf.body}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "evidence" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ background: theme.card, border: `1px solid ${theme.border}`, borderRadius: 12, padding: 18, marginBottom: 4 }}>
              <div style={{ fontSize: 11, color: theme.muted, marginBottom: 4 }}>SEC Filing Indexed</div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{{FILING_TITLE}}</div>
              <div style={{ fontSize: 12, color: theme.muted, marginTop: 2 }}>{sourcesEDGAR}</div>
            </div>
            {{EVIDENCE_ITEMS}}
          </div>
        )}

        {tab === "valuation" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ background: theme.card, border: `1px solid ${theme.border}`, borderRadius: 12, padding: 22 }}>
              <div style={{ fontSize: 12, color: theme.accent, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 18 }}>Valuation Scenarios</div>
              <div style={{ display: "grid", gridTemplateColumns: `repeat(${valuationScenarios.length}, 1fr)`, gap: 12 }}>
                {valuationScenarios.map((s) => (
                  <div key={s.label} style={{ background: s.color + "0D", border: `1px solid ${s.color}33`, borderRadius: 10, padding: 16 }}>
                    <div style={{ fontSize: 11, color: s.color, fontWeight: 700, textTransform: "uppercase", marginBottom: 8 }}>{s.label}</div>
                    <div style={{ fontSize: 28, fontWeight: 700, color: theme.fg, marginBottom: 4 }}>{s.price}</div>
                    <div style={{ fontSize: 13, color: s.color, fontWeight: 600, marginBottom: 10 }}>{s.updown}</div>
                    <div style={{ fontSize: 12, color: theme.muted, lineHeight: 1.5 }}>{s.desc}</div>
                  </div>
                ))}
              </div>
              {{VALUATION_FOOTER}}
            </div>
          </div>
        )}

        {tab === "revisit" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ background: theme.card, border: `1px solid ${theme.border}`, borderRadius: 12, padding: 22 }}>
              <h2 style={{ fontSize: 22, fontWeight: 700, color: theme.fg, margin: "0 0 20px 0" }}>Revisit Triggers</h2>
              <p style={{ fontSize: 13, color: theme.muted, margin: "0 0 16px 0", lineHeight: 1.6 }}>
                If any of these conditions are met, this name should be re-evaluated for a potential Add verdict.
              </p>
              {revisitTriggers.map((t, i) => (
                <div key={i} style={{ display: "flex", gap: 12, marginBottom: 10, padding: "12px 14px", background: "rgba(66,190,101,0.06)", borderRadius: 8, border: "1px solid rgba(66,190,101,0.15)" }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: theme.green, flexShrink: 0 }}>{i + 1}.</span>
                  <span style={{ fontSize: 13, color: theme.fg, lineHeight: 1.5 }}>{t}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* SOURCES */}
        <div style={{ marginTop: 32, padding: "16px 20px", background: theme.card, border: `1px solid ${theme.border}`, borderRadius: 10 }}>
          <div style={{ fontSize: 11, color: theme.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Sources</div>
          <div style={{ fontSize: 11, color: theme.muted, lineHeight: 1.6 }}>{citationsShort}</div>
        </div>

        {/* FOOTER */}
        <div style={{ marginTop: 32, padding: "14px 0", borderTop: `1px solid ${theme.border}`, display: "flex", justifyContent: "space-between", fontSize: 11, color: theme.muted }}>
          <span>Clarion Intelligence Systems LLC -- Research only, not investment advice</span>
          <span>Price: yfinance -- SEC: EDGAR ({{ACCESSION}}) -- {dataTs}</span>
        </div>
      </div>
    </div>
  );
}
