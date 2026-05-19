import { useState } from "react";

/*
 * FULL THESIS ZO SPACE TEMPLATE
 * ==============================
 * USAGE: Replace all {{PLACEHOLDER}} values with ticker-specific data.
 * RULES:
 *   - NO unicode escape sequences (\u2019, \u201c, \u201d, \u2014, etc.).
 *     Use plain ASCII quotes/apostrophes/dashes only.
 *   - 5 required tabs: Core Thesis, SEC Evidence, Valuation,
 *     Position Mgmt, Screener.
 *   - Theme colors should reflect the company's visual identity.
 *   - The TICKER_LOGO placeholder can be an SVG or text tile.
 */

// ---- THEME (per-ticker customization, mark the company's colors) ----
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
function fmt(n: number) { return n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2}); }
function fmtB(n: number) { if(n>=1e12) return `$${(n/1e12).toFixed(2)}T`; if(n>=1e9) return `$${(n/1e9).toFixed(0)}B`; return `$${n}`; }

// ---- KILL CONDITIONS ----
const killConditions: { n: string; condition: string; monitor: string }[] = [
  {{KILL_CONDITIONS}}
];

// ---- THESIS PILLARS (What I Believe) ----
const thesisPillars: { heading: string; detail: string }[] = [
  {{THESIS_PILLARS}}
];

// ---- SEC EVIDENCE ITEMS ----
const evidenceItems: { n: number; tag: string; section: string; quote: string }[] = [
  {{EVIDENCE_ITEMS}}
];

// ---- VALUATION SCENARIOS (Bear / Base / Bull) ----
const valuationScenarios: { label: string; color: string; fv: number; usd: string; pct: string; assumptions: string }[] = [
  {{VALUATION_SCENARIOS}}
];

// ---- SCREENER FACTORS ----
const screenerFactors: { key: string; weight: number; raw: string; score: number | null; note: string }[] = [
  {{SCREENER_FACTORS}}
];

// ---- SCREENER THRESHOLDS ----
const screenerThresholds: { check: string; actual: string; pass: boolean; note: string }[] = [
  {{SCREENER_THRESHOLDS}}
];

// ---- SCREENER SUMMARY ----
const screenerSummary: [string, string][] = [
  {{SCREENER_SUMMARY}}
];

// ---- TEXT BLOCKS ----
const thesisOneLiner = "{{THESIS_ONE_LINER}}";
const filingTitle = "{{FILING_TITLE}}";
const sourcesEDGAR = "{{SOURCES_EDGAR}}";

// ---- COMPONENT ----
export default function {{COMPONENT_NAME}}() {
  const [tab, setTab] = useState<"thesis"|"evidence"|"valuation"|"position"|"screener">("thesis");

  const scoreColor = (s: number|null) => s === null ? theme.muted : s >= 70 ? theme.green : s >= 30 ? theme.accent : theme.red;

  return (
    <div style={{ background: theme.bg, color: theme.fg, fontFamily: "'Inter', system-ui, sans-serif", minHeight: "100vh" }}>
      {/* NAV */}
      <div style={{ borderBottom: `1px solid ${theme.border}`, padding: "12px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(0,0,0,0.6)" }}>
        <span style={{ fontSize: 12, color: theme.muted, letterSpacing: "0.08em", textTransform: "uppercase" }}>Clarion Intelligence Systems</span>
        <span style={{ fontSize: 11, color: theme.muted }}>{{REGIME_LINE}}</span>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 20px" }}>
        {/* HERO */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 20, marginBottom: 28 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
              {{TICKER_LOGO}}
              <div>
                <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: "0.02em" }}>{{TICKER}}</div>
                <div style={{ fontSize: 13, color: theme.muted }}>{{COMPANY_NAME}}</div>
              </div>
            </div>
            <div style={{ fontSize: 12, color: theme.muted, background: theme.accentSoft, border: `1px solid ${theme.border}`, borderRadius: 6, padding: "4px 10px", display: "inline-block" }}>
              {{BUCKET}} Bucket -- {{STATUS}} -- Opened {{OPENED_DATE}}
            </div>
            {{SPECIAL_ALERTS}}
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 42, fontWeight: 700, letterSpacing: "-0.03em" }}>${fmt(price)}</div>
            <div style={{ fontSize: 16, color: change >= 0 ? theme.green : theme.red, fontWeight: 600 }}>
              {change >= 0 ? "▲" : "▼"} ${Math.abs(change).toFixed(2)} ({Math.abs(changePct).toFixed(2)}%)
            </div>
            <div style={{ fontSize: 11, color: theme.muted, marginTop: 4 }}>Close {timestamp} -- via yfinance -- {dataTs}</div>
            {{PRICE_RANGE_LINE}}
          </div>
        </div>

        {{ALERT_BANNER}}

        {/* THESIS ONE-LINER */}
        <div style={{ background: `linear-gradient(135deg,${theme.accentSoft},rgba(66,190,101,0.05))`, border: `1px solid ${theme.border}`, borderRadius: 12, padding: "18px 22px", marginBottom: 24 }}>
          <div style={{ fontSize: 11, color: theme.accent, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Thesis</div>
          <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.4 }}>{thesisOneLiner}</div>
        </div>

        {/* STATS BAR */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 10, marginBottom: 24 }}>
          {{STATS_BAR_ITEMS}}
        </div>

        {{PRICE_RANGE_BAR}}

        {/* TABS */}
        <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: `1px solid ${theme.border}` }}>
          {(["thesis","evidence","valuation","position","screener"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ padding: "10px 18px", background: "none", border: "none", cursor: "pointer", fontSize: 13, fontWeight: tab===t?700:400, color: tab===t?theme.accent:theme.muted, borderBottom: tab===t?`2px solid ${theme.accent}`:"2px solid transparent", textTransform: "capitalize" }}>
              {t==="thesis"?"Core Thesis":t==="evidence"?"SEC Evidence":t==="valuation"?"Valuation":t==="position"?"Position Mgmt":"Screener"}
            </button>
          ))}
        </div>

        {/* TAB: CORE THESIS */}
        {tab==="thesis" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ background: theme.card, border: `1px solid ${theme.border}`, borderRadius: 12, padding: 22 }}>
              <div style={{ fontSize: 12, color: theme.accent, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>What I Believe</div>
              {{THESIS_PROSE}}
              {thesisPillars.map(({heading, detail}) => (
                <div key={heading} style={{ display: "flex", gap: 12, marginBottom: 12 }}>
                  <div style={{ width: 3, background: theme.accent, borderRadius: 2, flexShrink: 0 }}/>
                  <div><span style={{ fontWeight: 600, color: theme.accent, fontSize: 13 }}>{heading}: </span><span style={{ fontSize: 13, color: theme.muted, lineHeight: 1.6 }}>{detail}</span></div>
                </div>
              ))}
            </div>
            <div style={{ background: theme.card, border: "1px solid rgba(250,77,86,0.25)", borderRadius: 12, padding: 22 }}>
              <div style={{ fontSize: 12, color: theme.kill, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>Kill Conditions</div>
              {killConditions.map(({n, condition, monitor}) => (
                <div key={n} style={{ display:"flex",alignItems:"flex-start",gap:12,marginBottom:10,padding:"10px 14px",background:"rgba(250,77,86,0.06)",borderRadius:8,border:"1px solid rgba(250,77,86,0.12)" }}>
                  <div style={{ width:22,height:22,borderRadius:"50%",background:"rgba(250,77,86,0.2)",color:theme.kill,fontSize:11,fontWeight:700,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0 }}>{n}</div>
                  <div><div style={{ fontSize:13,color:theme.fg,fontWeight:500 }}>{condition}</div><div style={{ fontSize:11,color:theme.muted,marginTop:2 }}>Monitor: {monitor}</div></div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB: SEC EVIDENCE */}
        {tab==="evidence" && (
          <div style={{ display:"flex",flexDirection:"column",gap:12 }}>
            <div style={{ background:theme.card,border:`1px solid ${theme.border}`,borderRadius:12,padding:18,marginBottom:4 }}>
              <div style={{ fontSize:11,color:theme.muted,marginBottom:4 }}>SEC Filing Indexed</div>
              <div style={{ fontSize:14,fontWeight:600 }}>{filingTitle}</div>
              <div style={{ fontSize:12,color:theme.muted,marginTop:2 }}>{sourcesEDGAR}</div>
            </div>
            {evidenceItems.map(({n,tag,section,quote}) => (
              <div key={n} style={{ background:theme.card,border:`1px solid ${theme.border}`,borderRadius:10,padding:16 }}>
                <div style={{ display:"flex",alignItems:"center",gap:8,marginBottom:8 }}>
                  <span style={{ background:theme.accentSoft,color:theme.accent,fontSize:10,fontWeight:700,padding:"2px 8px",borderRadius:4,textTransform:"uppercase" }}>{tag}</span>
                  <span style={{ fontSize:11,color:theme.muted }}>{section}</span>
                </div>
                <p style={{ fontSize:13,color:theme.muted,margin:0,lineHeight:1.65,fontStyle:"italic" }}>"{quote}"</p>
              </div>
            ))}
          </div>
        )}

        {/* TAB: VALUATION */}
        {tab==="valuation" && (
          <div style={{ display:"flex",flexDirection:"column",gap:16 }}>
            <div style={{ background:theme.card,border:`1px solid ${theme.border}`,borderRadius:12,padding:22 }}>
              <div style={{ fontSize:12,color:theme.accent,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:16 }}>Bear / Base / Bull</div>
              <div style={{ display:"grid",gridTemplateColumns:`repeat(${valuationScenarios.length},1fr)`,gap:12 }}>
                {valuationScenarios.map(s => {
                  const isBear = s.label === "Bear";
                  const isBase = s.label === "Base";
                  const rgba = isBear ? "250,77,86" : isBase ? "15,98,254" : "66,190,101";
                  return (
                    <div key={s.label} style={{ background:`rgba(${rgba},0.07)`,border:`1px solid rgba(${rgba},0.25)`,borderRadius:10,padding:16 }}>
                      <div style={{ fontSize:11,color:s.color,fontWeight:700,textTransform:"uppercase",marginBottom:8 }}>{s.label}</div>
                      <div style={{ fontSize:32,fontWeight:700,color:theme.fg,marginBottom:4 }}>${s.fv}</div>
                      <div style={{ fontSize:14,color:s.color,fontWeight:600,marginBottom:10 }}>{s.usd} ({s.pct})</div>
                      <div style={{ fontSize:12,color:theme.muted,lineHeight:1.5 }}>{s.assumptions}</div>
                    </div>
                  );
                })}
              </div>
              {{VALUATION_FOOTER}}
            </div>
          </div>
        )}

        {/* TAB: POSITION MGMT */}
        {tab==="position" && (
          <div style={{ display:"flex",flexDirection:"column",gap:14 }}>
            <div style={{ display:"grid",gridTemplateColumns:"1fr 1fr",gap:14 }}>
              <div style={{ background:theme.card,border:`1px solid ${theme.border}`,borderRadius:12,padding:18 }}>
                <div style={{ fontSize:12,color:theme.accent,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:12 }}>Sizing</div>
                {{SIZING_ROWS}}
              </div>
              <div style={{ background:theme.card,border:`1px solid ${theme.border}`,borderRadius:12,padding:18 }}>
                <div style={{ fontSize:12,color:theme.accent,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:12 }}>Entry / Exit Levels</div>
                {{ENTRY_EXIT_ROWS}}
              </div>
            </div>
            {{POSITION_NARRATIVE}}
          </div>
        )}

        {/* TAB: SCREENER */}
        {tab === "screener" && (
          <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:12 }}>
              {screenerSummary.map(([l,v])=>(
                <div key={l} style={{ background:theme.card, border:`1px solid ${theme.border}`, borderRadius:10, padding:"14px 16px", textAlign:"center" }}>
                  <div style={{ fontSize:22, fontWeight:700, color:theme.accent }}>{v}</div>
                  <div style={{ fontSize:11, color:theme.muted, marginTop:4, textTransform:"uppercase", letterSpacing:"0.06em" }}>{l}</div>
                </div>
              ))}
            </div>
            <div style={{ background:"rgba(250,77,86,0.07)", border:"1px solid rgba(250,77,86,0.3)", borderRadius:12, padding:"16px 20px" }}>
              <div style={{ fontSize:12, color:theme.kill, fontWeight:700, textTransform:"uppercase", letterSpacing:"0.08em", marginBottom:12 }}>Regime Threshold Filter</div>
              {screenerThresholds.map(t=>{
                const bg=t.pass?"rgba(66,190,101,0.06)":"rgba(250,77,86,0.08)";
                const br=t.pass?"1px solid rgba(66,190,101,0.2)":"1px solid rgba(250,77,86,0.2)";
                return (
                  <div key={t.check} style={{ display:"flex", alignItems:"center", gap:12, padding:"8px 12px", background:bg, borderRadius:8, border:br, marginBottom:6 }}>
                    <span style={{ fontSize:16, width:20, flexShrink:0 }}>{t.pass?"✓":"✗"}</span>
                    <span style={{ fontSize:13, fontWeight:600, color:t.pass?theme.green:theme.kill, width:150, flexShrink:0 }}>{t.check}</span>
                    <span style={{ fontSize:12, color:theme.muted, width:90, flexShrink:0 }}>-- <strong style={{ color:theme.fg }}>{t.actual}</strong></span>
                    <span style={{ fontSize:12, color:theme.muted }}>{t.note}</span>
                  </div>
                );
              })}
              {{THESIS_OVERRIDE}}
            </div>
            <div style={{ background:theme.card, border:`1px solid ${theme.border}`, borderRadius:12, padding:"18px 20px" }}>
              <div style={{ fontSize:12, color:theme.accent, textTransform:"uppercase", letterSpacing:"0.08em", marginBottom:10 }}>Per-Factor Breakdown</div>
              <div style={{ fontSize:11, color:theme.muted, marginBottom:14, padding:"8px 12px", background:theme.accentSoft, borderRadius:6 }}>
                {{SCREENER_FORMULA_LINE}}
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"16px 110px 40px 90px 72px 1fr 190px", gap:8, padding:"6px 10px", marginBottom:4 }}>
                {["","Factor","Wt","Raw","Score /100","","Notes"].map((h,i)=>( <span key={i} style={{ fontSize:10, color:theme.muted, textTransform:"uppercase", letterSpacing:"0.06em" }}>{h}</span> ))}
              </div>
              {screenerFactors.map(f=>(
                <div key={f.key} style={{ display:"grid", gridTemplateColumns:"16px 110px 40px 90px 72px 1fr 190px", alignItems:"center", gap:8, padding:"8px 10px", background:"rgba(255,255,255,0.02)", borderRadius:8, marginBottom:4 }}>
                  <div style={{ width:8, height:8, borderRadius:"50%", background:scoreColor(f.score) }}/>
                  <span style={{ fontSize:13, fontWeight:600 }}>{f.key}</span>
                  <span style={{ fontSize:12, color:theme.muted, textAlign:"center" }}>{f.weight}%</span>
                  <span style={{ fontSize:12, color:theme.muted, textAlign:"center" }}>{f.raw}</span>
                  <span style={{ fontSize:14, fontWeight:700, color:scoreColor(f.score), textAlign:"center" }}>{f.score===null?"--":f.score}</span>
                  <div style={{ background:"rgba(255,255,255,0.08)", borderRadius:4, height:6 }}>
                    {f.score!==null && <div style={{ background:scoreColor(f.score), borderRadius:4, height:"100%", width:`${f.score}%` }}/>}
                  </div>
                  <span style={{ fontSize:11, color:theme.muted, lineHeight:1.4 }}>{f.note}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* FOOTER */}
        <div style={{ marginTop:32,padding:"14px 0",borderTop:`1px solid ${theme.border}`,display:"flex",justifyContent:"space-between",fontSize:11,color:theme.muted }}>
          <span>Clarion Intelligence Systems LLC -- Research only, not investment advice</span>
          <span>Price: yfinance -- SEC: EDGAR ({{ACCESSION}}) -- {dataTs}</span>
        </div>
      </div>
    </div>
  );
}
