import { useState } from "react";
const theme = { fg: "#fff", muted: "#999", accent: "#f50", border: "#282828" };
export default function P() {
  const [tab, setTab] = useState("thesis");
  const tabs = ["Core Thesis", "SEC Evidence", "Valuation", "Position Mgmt", "Screener"];
  return (
    <div>
      <a href="https://cis.zo.space/">Clarion Intelligence Systems</a>
      {tabs.map(t => (
        <button key={t} onClick={() => setTab(t.toLowerCase().replace(/ /g, ""))}>{t}</button>
      ))}
      {tab === "thesis" && <div>Core Thesis body</div>}
      {tab === "evidence" && <div>SEC Evidence body</div>}
      {tab === "valuation" && <div>Valuation body</div>}
      {tab === "position" && <div>Position Mgmt body</div>}
      {tab === "screener" && <div>Screener body</div>}
    </div>
  );
}
