import { useRef, useEffect, useState } from "react";
import { motion, useScroll, useTransform } from "framer-motion";

const FEATURES = [
  { tag: "01 / REGIME", title: "HIDDEN MARKOV MODEL", sub: "Classifies every market in real-time — BULL, BEAR, NEUTRAL, CRISIS, HIGH_VOL — across US, India, and Crypto. Concept drift detection included.", accent: "#FFE600" },
  { tag: "02 / SENTIMENT", title: "FINBERT SCORING", sub: "NLP scoring of news + Reddit. Tracks narrative arcs from Emerging → Fading. Cross-asset spillover detection.", accent: "#00FFCC" },
  { tag: "03 / ENSEMBLE", title: "4-STRATEGY ROUTING", sub: "Momentum · Mean Reversion · Volatility · Crisis. Each activates in its optimal regime and fires independent signals.", accent: "#FF6B35" },
  { tag: "04 / DEBATE", title: "AI DEBATE ENGINE", sub: "4 specialist AIs argue every trade. Requires 60%+ consensus + 3 of 4 FOR votes before anything executes.", accent: "#C084FC" },
  { tag: "05 / RISK", title: "7-LAYER RISK STACK", sub: "Pre-trade · VaR · Kill Switch · Compliance · Ops · Debate Consensus · CIO. Real-time drawdown tracking.", accent: "#F87171" },
  { tag: "06 / CIO", title: "DUAL CIO MODES", sub: "Be the CIO with natural language chat, or delegate to an AI CIO that monitors all 12 agents autonomously.", accent: "#34D399" },
];

const DEPTS = [
  { name: "FRONT OFFICE", tag: "Investment & Revenue", agents: ["Regime Agent", "Sentiment Agent", "Ensemble Selector", "Execution Agent", "Portfolio Agent", "IR Agent"], count: "6 AGENTS", color: "#FFE600" },
  { name: "MIDDLE OFFICE", tag: "Risk & Control", agents: ["Risk Agent", "Compliance Agent", "Operations Agent"], count: "3 AGENTS", color: "#00FFCC" },
  { name: "BACK OFFICE", tag: "Support & Finance", agents: ["Accounting Agent", "IT Agent", "Quant Agent"], count: "3 AGENTS", color: "#FF6B35" },
  { name: "EXECUTIVE", tag: "Management", agents: ["AI CIO (autonomous)", "Human CIO (interactive)"], count: "2 MODES", color: "#C084FC" },
];

const INSTALL_STEPS = [
  { n: "01", title: "CLONE", code: "git clone https://github.com/your-username/horizon-capital.git\ncd horizon-capital/backend" },
  { n: "02", title: "INSTALL", code: "python -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt" },
  { n: "03", title: "CONFIGURE", code: "ANTHROPIC_API_KEY=sk-ant-...\nOPENAI_API_KEY=sk-...\nSYSTEM_MODE=PAPER_TRADING" },
  { n: "04", title: "RUN", code: "python -m app\n# or headless:\npython -m app --headless" },
];

function Cursor() {
  const [pos, setPos] = useState({ x: -100, y: -100 });
  useEffect(() => {
    const move = (e) => setPos({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", move);
    return () => window.removeEventListener("mousemove", move);
  }, []);
  return (
    <motion.div
      className="fixed top-0 left-0 pointer-events-none z-[9999] mix-blend-difference"
      animate={{ x: pos.x - 6, y: pos.y - 6 }}
      transition={{ type: "spring", stiffness: 500, damping: 28, mass: 0.5 }}
    >
      <div style={{ width: 12, height: 12, background: "white", borderRadius: "50%" }} />
    </motion.div>
  );
}

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const fn = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", fn);
    return () => window.removeEventListener("scroll", fn);
  }, []);
  return (
    <nav style={{ position: "fixed", top: 0, left: 0, right: 0, zIndex: 100, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 2.5rem", height: 56, borderBottom: scrolled ? "1px solid rgba(255,255,255,0.1)" : "1px solid transparent", background: scrolled ? "rgba(0,0,0,0.92)" : "transparent", backdropFilter: scrolled ? "blur(12px)" : "none", transition: "all 0.4s" }}>
      <a href="#" style={{ fontFamily: "'Inter', sans-serif", fontSize: "0.82rem", letterSpacing: "0.22em", fontWeight: 900, color: "white", textDecoration: "none" }}>HORIZON CAPITAL</a>
      <div style={{ display: "flex", gap: "2rem", alignItems: "center", fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem", letterSpacing: "0.14em" }}>
        {["Features", "Architecture", "Install", "Docs"].map(l => (
          <a key={l} href={`#${l.toLowerCase()}`} style={{ color: "rgba(255,255,255,0.35)", textDecoration: "none", transition: "color 0.2s" }}
            onMouseEnter={e => e.currentTarget.style.color = "white"} onMouseLeave={e => e.currentTarget.style.color = "rgba(255,255,255,0.35)"}>
            {l.toUpperCase()}
          </a>
        ))}
        <a href="https://github.com" target="_blank" rel="noopener" style={{ color: "white", border: "1px solid rgba(255,255,255,0.2)", padding: "0.3rem 0.9rem", textDecoration: "none", transition: "all 0.2s" }}
          onMouseEnter={e => { e.currentTarget.style.background = "white"; e.currentTarget.style.color = "black"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "white"; }}>
          GITHUB ↗
        </a>
      </div>
    </nav>
  );
}

function MarqueeBar({ items, speed = 30 }) {
  const doubled = [...items, ...items];
  return (
    <div style={{ overflow: "hidden", whiteSpace: "nowrap", borderTop: "1px solid rgba(255,255,255,0.07)", borderBottom: "1px solid rgba(255,255,255,0.07)", padding: "0.75rem 0" }}>
      <motion.div
        style={{ display: "inline-flex", gap: "3rem", fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", letterSpacing: "0.2em", color: "rgba(255,255,255,0.2)" }}
        animate={{ x: ["0%", "-50%"] }}
        transition={{ repeat: Infinity, duration: speed, ease: "linear" }}
      >
        {doubled.map((item, i) => (<span key={i}>{item} <span style={{ color: "rgba(255,255,255,0.08)", margin: "0 1rem" }}>◆</span></span>))}
      </motion.div>
    </div>
  );
}

function BigWord({ children, style = {}, delay = 0, once = true }) {
  return (
    <motion.div
      style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, lineHeight: 0.92, letterSpacing: "-0.03em", ...style }}
      initial={{ opacity: 0, y: 60 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once }}
      transition={{ duration: 0.8, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}

function HeroSection() {
  const { scrollYProgress } = useScroll();
  const opacity = useTransform(scrollYProgress, [0, 0.22], [1, 0]);
  const y = useTransform(scrollYProgress, [0, 0.22], [0, -40]);
  const [count, setCount] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setCount(c => (c >= 12 ? 12 : c + 1)), 100);
    return () => clearInterval(t);
  }, []);

  return (
    <motion.section style={{ minHeight: "100vh", display: "flex", flexDirection: "column", justifyContent: "center", position: "relative", overflow: "hidden", padding: "120px 3rem 80px", opacity, y }}>
      <div style={{ position: "absolute", inset: 0, backgroundImage: "linear-gradient(rgba(255,255,255,0.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.025) 1px,transparent 1px)", backgroundSize: "80px 80px", pointerEvents: "none" }} />

      <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "3rem", fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem", letterSpacing: "0.2em" }}>
        <span style={{ color: "rgba(255,255,255,0.25)" }}>v0.2.0</span>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#34D399", animation: "pulse 1.5s ease-in-out infinite" }} />
        <span style={{ color: "rgba(255,255,255,0.25)" }}>OPEN SOURCE · MIT</span>
      </motion.div>

      <div style={{ marginBottom: "2rem" }}>
        <BigWord style={{ fontSize: "clamp(4.5rem, 14vw, 15rem)", color: "white" }} delay={0.1}>YOUR</BigWord>
        <BigWord style={{ fontSize: "clamp(4.5rem, 14vw, 15rem)", color: "transparent", WebkitTextStroke: "1.5px rgba(255,255,255,0.12)" }} delay={0.2}>AI HEDGE</BigWord>
        <BigWord style={{ fontSize: "clamp(4.5rem, 14vw, 15rem)", color: "white" }} delay={0.3}>FUND.</BigWord>
      </div>

      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.7 }} style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: "2rem", flexWrap: "wrap" }}>
        <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.85rem", color: "rgba(255,255,255,0.32)", maxWidth: 360, lineHeight: 1.85, letterSpacing: "0.02em" }}>
          <span style={{ color: "#FFE600" }}>{count}</span> AI agents · 4 departments · 0 infrastructure.<br />
          Autonomous hedge fund that runs in your terminal.
        </p>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <a href="#install" style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", letterSpacing: "0.15em", padding: "0.85rem 2rem", background: "white", color: "black", fontWeight: 700, textDecoration: "none", transition: "all 0.2s", display: "inline-block" }}
            onMouseEnter={e => e.currentTarget.style.background = "#FFE600"} onMouseLeave={e => e.currentTarget.style.background = "white"}>
            INSTALL →
          </a>
          <a href="#features" style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", letterSpacing: "0.15em", padding: "0.85rem 2rem", border: "1px solid rgba(255,255,255,0.2)", color: "rgba(255,255,255,0.6)", textDecoration: "none", transition: "all 0.2s" }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "white"; e.currentTarget.style.color = "white"; }} onMouseLeave={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.2)"; e.currentTarget.style.color = "rgba(255,255,255,0.6)"; }}>
            FEATURES
          </a>
        </div>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.9 }} style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, marginTop: "4rem", background: "rgba(255,255,255,0.05)" }}>
        {[["12+", "AI Agents"], ["4", "Departments"], ["3", "LLM Providers"], ["0", "Infra Required"]].map(([n, l]) => (
          <div key={l} style={{ background: "black", padding: "1.5rem 1.75rem" }}>
            <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, fontSize: "2rem", color: "white", marginBottom: "0.25rem" }}>{n}</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "rgba(255,255,255,0.25)", letterSpacing: "0.14em", textTransform: "uppercase" }}>{l}</div>
          </div>
        ))}
      </motion.div>
    </motion.section>
  );
}

function FeatureRow({ feat, i }) {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const opacity = useTransform(scrollYProgress, [0.05, 0.25, 0.75, 0.95], [0, 1, 1, 0]);
  const x = useTransform(scrollYProgress, [0.05, 0.25], [-50, 0]);
  const [hovered, setHovered] = useState(false);

  return (
    <motion.div ref={ref} style={{ opacity, x, minHeight: "55vh", display: "flex", flexDirection: "column", justifyContent: "center", borderBottom: "1px solid rgba(255,255,255,0.06)", padding: "5rem 3rem" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: "3rem" }}>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", letterSpacing: "0.18em", color: "rgba(255,255,255,0.2)", paddingTop: "1rem", width: "6rem", flexShrink: 0 }}>{feat.tag}</span>
        <div style={{ flex: 1 }}>
          <div
            style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, lineHeight: 0.92, fontSize: "clamp(2.5rem, 6vw, 6.5rem)", color: hovered ? feat.accent : "white", transition: "color 0.3s", cursor: "default", letterSpacing: "-0.02em", marginBottom: "1.5rem" }}
            onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
          >
            {feat.title}
          </div>
          <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.82rem", color: "rgba(255,255,255,0.35)", maxWidth: 520, lineHeight: 1.85, letterSpacing: "0.02em" }}>{feat.sub}</p>
        </div>
        <div style={{ flexShrink: 0, fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "rgba(255,255,255,0.08)", paddingTop: "1rem" }}>
          {String(i + 1).padStart(2, "0")} / {String(FEATURES.length).padStart(2, "0")}
        </div>
      </div>
    </motion.div>
  );
}

function FeaturesSection() {
  return (
    <section id="features">
      <div style={{ overflow: "hidden", paddingLeft: "1rem" }}>
        <BigWord style={{ fontSize: "clamp(5rem, 20vw, 20rem)", color: "transparent", WebkitTextStroke: "1px rgba(255,255,255,0.05)", letterSpacing: "-0.04em", lineHeight: 0.85 }}>
          FEATURES
        </BigWord>
      </div>
      <div style={{ marginTop: "-2rem" }}>
        {FEATURES.map((f, i) => <FeatureRow key={i} feat={f} i={i} />)}
      </div>
    </section>
  );
}

function ArchSection() {
  return (
    <section id="architecture" style={{ padding: "6rem 3rem" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: "2rem", marginBottom: "3rem" }}>
        <BigWord style={{ fontSize: "clamp(2.5rem, 7vw, 6rem)", color: "white" }}>ARCHITECTURE</BigWord>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "rgba(255,255,255,0.2)", letterSpacing: "0.18em", marginBottom: "1rem" }}>4 DEPARTMENTS · 12 AGENTS</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 1, background: "rgba(255,255,255,0.06)" }}>
        {DEPTS.map((d, i) => (
          <motion.div key={i} style={{ background: "black", padding: "2.5rem" }}
            initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.1 }}
            whileHover={{ backgroundColor: "rgba(255,255,255,0.02)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
              <div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", letterSpacing: "0.2em", color: d.color, marginBottom: "0.5rem" }}>{d.tag.toUpperCase()}</div>
                <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, fontSize: "1.4rem", color: "white", letterSpacing: "-0.01em" }}>{d.name}</div>
              </div>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "rgba(255,255,255,0.15)", letterSpacing: "0.12em" }}>{d.count}</span>
            </div>
            <ul style={{ listStyle: "none" }}>
              {d.agents.map((a, j) => (
                <li key={j} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem", color: "rgba(255,255,255,0.3)", display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.5rem" }}>
                  <span style={{ color: d.color, fontSize: "0.5rem" }}>▶</span>{a}
                </li>
              ))}
            </ul>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

function MarketsSection() {
  const markets = [
    { flag: "IN", name: "INDIA NSE", symbols: "RELIANCE · TCS · INFY · HDFCBANK", broker: "ZERODHA", color: "#FF9933" },
    { flag: "US", name: "US NASDAQ", symbols: "AAPL · MSFT · GOOGL · AMZN · TSLA", broker: "ALPACA", color: "#3B82F6" },
    { flag: "₿", name: "CRYPTO", symbols: "BTC-USD · ETH-USD", broker: "PAPER / API", color: "#F7931A" },
  ];
  return (
    <section style={{ padding: "0 3rem 6rem", overflow: "hidden" }}>
      <BigWord style={{ fontSize: "clamp(5rem, 18vw, 16rem)", color: "transparent", WebkitTextStroke: "1px rgba(255,255,255,0.05)", marginBottom: "-1rem", letterSpacing: "-0.04em" }}>
        MARKETS
      </BigWord>
      <div style={{ display: "flex", gap: 1, background: "rgba(255,255,255,0.06)" }}>
        {markets.map((m, i) => (
          <motion.div key={i} style={{ flex: 1, background: "black", padding: "2.5rem", position: "relative", overflow: "hidden", border: "1px solid rgba(255,255,255,0.06)", cursor: "default" }}
            initial={{ opacity: 0, x: 40 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.15 }}>
            <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, fontSize: "5rem", lineHeight: 1, marginBottom: "1.25rem", color: "rgba(255,255,255,0.08)" }}>{m.flag}</div>
            <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, fontSize: "1.2rem", color: "white", marginBottom: "0.5rem" }}>{m.name}</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", color: "rgba(255,255,255,0.25)", marginBottom: "1.25rem", letterSpacing: "0.08em" }}>{m.symbols}</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", letterSpacing: "0.15em", padding: "0.3rem 0.7rem", display: "inline-block", border: `1px solid ${m.color}40`, color: m.color }}>{m.broker}</div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

function InstallSection() {
  const [copied, setCopied] = useState(null);
  const copy = (text, idx) => { navigator.clipboard.writeText(text); setCopied(idx); setTimeout(() => setCopied(null), 2000); };
  return (
    <section id="install" style={{ padding: "6rem 3rem" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: "2rem", marginBottom: "3rem" }}>
        <BigWord style={{ fontSize: "clamp(2.5rem, 7vw, 6rem)", color: "white" }}>INSTALL</BigWord>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "rgba(255,255,255,0.2)", letterSpacing: "0.18em", marginBottom: "1rem" }}>UNDER 2 MINUTES · ZERO INFRA</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        {INSTALL_STEPS.map((step, i) => (
          <motion.div key={i} style={{ display: "flex", gap: 0, border: "1px solid rgba(255,255,255,0.07)" }}
            initial={{ opacity: 0, x: -40 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.1 }}>
            <div style={{ width: 64, flexShrink: 0, display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "1.75rem", borderRight: "1px solid rgba(255,255,255,0.07)" }}>
              <span style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, fontSize: "2rem", color: "rgba(255,255,255,0.06)" }}>{step.n}</span>
            </div>
            <div style={{ flex: 1, padding: "1.5rem 1.75rem" }}>
              <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 700, fontSize: "0.7rem", letterSpacing: "0.2em", color: "rgba(255,255,255,0.3)", marginBottom: "0.75rem" }}>{step.title}</div>
              <pre style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.78rem", color: "rgba(255,255,255,0.5)", lineHeight: 1.7, whiteSpace: "pre-wrap", margin: 0 }}>{step.code}</pre>
            </div>
            <button onClick={() => copy(step.code, i)} style={{ width: 60, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", borderLeft: "1px solid rgba(255,255,255,0.07)", fontFamily: "'JetBrains Mono', monospace", fontSize: "0.6rem", color: copied === i ? "#34D399" : "rgba(255,255,255,0.2)", background: "none", border: "none", borderLeft: "1px solid rgba(255,255,255,0.07)", cursor: "pointer", letterSpacing: "0.1em", transition: "color 0.2s" }}>
              {copied === i ? "✓" : "COPY"}
            </button>
          </motion.div>
        ))}
      </div>

      <div style={{ marginTop: "3rem" }}>
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", letterSpacing: "0.2em", color: "rgba(255,255,255,0.2)", marginBottom: "1rem" }}>SYSTEM MODES</div>
        <div style={{ display: "flex", gap: 1, background: "rgba(255,255,255,0.05)" }}>
          {[
            { name: "PAPER TRADING", desc: "Safe. Mock broker. No real money.", cmd: "--mode PAPER_TRADING", color: "#34D399" },
            { name: "HUMAN APPROVAL", desc: "Orders queue. You approve each trade.", cmd: "--mode HUMAN_APPROVAL", color: "#FFE600" },
            { name: "FULLY AUTONOMOUS", desc: "Full auto. Real brokers. Real money.", cmd: "--mode FULLY_AUTONOMOUS", color: "#F87171" },
          ].map((m, i) => (
            <div key={i} style={{ flex: 1, background: "black", padding: "2rem" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: m.color, marginBottom: "1rem" }} />
              <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 800, fontSize: "0.9rem", color: "white", marginBottom: "0.5rem" }}>{m.name}</div>
              <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", color: "rgba(255,255,255,0.28)", lineHeight: 1.7, marginBottom: "0.75rem" }}>{m.desc}</p>
              <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "rgba(255,255,255,0.18)" }}>{m.cmd}</code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function DocsSection() {
  const docs = [
    { title: "QUICK START", desc: "Install and run in under 2 minutes", href: "#install" },
    { title: "FULL DOCS", desc: "22-section comprehensive guide", href: "https://github.com" },
    { title: "ARCHITECTURE", desc: "Agent system, messaging, data flow", href: "https://github.com" },
    { title: "CONFIG REF", desc: "Every .env variable documented", href: "https://github.com" },
  ];
  return (
    <section id="docs" style={{ padding: "6rem 3rem", borderTop: "1px solid rgba(255,255,255,0.07)" }}>
      <BigWord style={{ fontSize: "clamp(3rem, 8vw, 7rem)", color: "white", marginBottom: "3rem" }}>DOCS</BigWord>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, background: "rgba(255,255,255,0.06)" }}>
        {docs.map((d, i) => (
          <a key={i} href={d.href} target={d.href.startsWith("http") ? "_blank" : undefined} rel="noopener"
            style={{ background: "black", padding: "2.5rem 2rem", textDecoration: "none", display: "block", transition: "background 0.2s" }}
            onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"} onMouseLeave={e => e.currentTarget.style.background = "black"}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", letterSpacing: "0.15em", color: "rgba(255,255,255,0.18)", marginBottom: "1rem" }}>0{i + 1}</div>
            <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, fontSize: "1.1rem", color: "white", marginBottom: "0.75rem", letterSpacing: "-0.01em" }}>{d.title} ↗</div>
            <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", color: "rgba(255,255,255,0.28)", lineHeight: 1.7 }}>{d.desc}</p>
          </a>
        ))}
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer style={{ padding: "4rem 3rem", borderTop: "1px solid rgba(255,255,255,0.07)", display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: "2rem" }}>
      <div>
        <div style={{ fontFamily: "'Inter', sans-serif", fontWeight: 900, fontSize: "4rem", color: "rgba(255,255,255,0.05)", lineHeight: 1, letterSpacing: "-0.04em" }}>HORIZON</div>
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "rgba(255,255,255,0.18)", letterSpacing: "0.18em" }}>CAPITAL · AUTONOMOUS AI HEDGE FUND · MIT LICENSE</div>
      </div>
      <div style={{ display: "flex", gap: "2rem", fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", letterSpacing: "0.12em" }}>
        {[["GITHUB ↗", "https://github.com"], ["INSTALL", "#install"], ["DOCS", "#docs"]].map(([label, href]) => (
          <a key={label} href={href} target={href.startsWith("http") ? "_blank" : undefined} rel="noopener"
            style={{ color: "rgba(255,255,255,0.22)", textDecoration: "none", transition: "color 0.2s" }}
            onMouseEnter={e => e.currentTarget.style.color = "white"} onMouseLeave={e => e.currentTarget.style.color = "rgba(255,255,255,0.22)"}>
            {label}
          </a>
        ))}
      </div>
    </footer>
  );
}

const MARQUEE_TOP = ["REGIME DETECTION", "SENTIMENT ANALYSIS", "4-STRATEGY ENSEMBLE", "AI DEBATE ENGINE", "7-LAYER RISK STACK", "CIO DUAL MODE", "FINBERT NLP", "HIDDEN MARKOV MODEL", "KELLY SIZING", "PAPER TRADING", "ALPACA BROKER", "ZERODHA BROKER", "AUTONOMOUS TRADING", "OPEN SOURCE", "MIT LICENSE"];
const MARQUEE_MID = ["12 AGENTS RUNNING", "RISK SYSTEMS ONLINE", "ALL DEPARTMENTS ACTIVE", "NAV $1,000,000.00", "KILL SWITCH OFF", "VaR 95% = 0.0234", "REGIME: US=BULL", "SIGNALS: 2 BUY, 1 SELL"];

export default function App() {
  return (
    <div style={{ background: "black", minHeight: "100vh", cursor: "none" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.3; } }
        ::-webkit-scrollbar { width: 4px; } ::-webkit-scrollbar-track { background: black; } ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); }
        ::selection { background: #FFE600; color: black; }
      `}</style>
      <Cursor />
      <Nav />
      <HeroSection />
      <MarqueeBar items={MARQUEE_TOP} speed={45} />
      <FeaturesSection />
      <MarqueeBar items={MARQUEE_MID} speed={22} />
      <ArchSection />
      <MarketsSection />
      <InstallSection />
      <DocsSection />
      <Footer />
    </div>
  );
}
