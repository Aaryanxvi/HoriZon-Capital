// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-DFB31DFA3EE1
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { ArrowRight, Check, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { runCommand, testAlpaca, useConfig, useOnboarding, useUpdateSettings } from "@/lib/api";
import { ErrorNote } from "@/components/ui";
import { useTour } from "@/components/Tour";

// Everything is written through /control/settings to backend/.env -- the same
// file and allow-list the Settings page and the terminal's `--setup` use.
const STEPS = ["Welcome", "Alpaca", "AI keys", "Configure", "Models", "Done"] as const;

const MODES = [
  { key: "PAPER_TRADING", label: "Paper trading", hint: "Orders fill straight away. Simplest start." },
  { key: "HUMAN_APPROVAL", label: "Human approval", hint: "Every order waits for your approve." },
  { key: "FULLY_AUTONOMOUS", label: "Fully autonomous", hint: "The AI debate decides. Needs an AI key." },
];

type Provider = "claude" | "openai" | "gemini";

// Model ids must exist in backend/app/llm/models_registry.py. Only the CIO model
// (per-agent override) and the debate model (DEBATE_MODEL) are settable; the
// other departments run their provider's default model.
const REC: Record<Provider, { name: string; cio: [string, string]; debate: [string, string]; fallback: string }> = {
  claude: {
    name: "Anthropic",
    cio: ["claude-opus-4-7", "Claude Opus 4.7"],
    debate: ["claude-haiku-4-5-20251001", "Claude Haiku 4.5"],
    fallback: "Claude Sonnet 4",
  },
  openai: {
    name: "OpenAI",
    cio: ["o3-mini", "o3-mini (reasoning)"],
    debate: ["gpt-4o-mini", "GPT-4o mini"],
    fallback: "GPT-4o",
  },
  gemini: {
    name: "Google",
    cio: ["gemini-2.5-pro", "Gemini 2.5 Pro"],
    debate: ["gemini-2.0-flash", "Gemini 2.0 Flash"],
    fallback: "Gemini 2.0 Flash",
  },
};

function modelRows(p: Provider) {
  const r = REC[p];
  return [
    { dept: "Executive · CIO", model: r.cio[1], effort: "High", why: "Few calls, highest stakes: crisis and override decisions." },
    { dept: "Middle office · debates", model: r.debate[1], effort: "Low", why: "~8 calls per debate; a fast model stays under rate limits." },
    { dept: "Front office · regime, sentiment, IR", model: `${r.fallback} (default)`, effort: "Low", why: "Frequent short reads; the default is plenty." },
    { dept: "Back office · quant research", model: `${r.fallback} (default)`, effort: "Medium", why: "Periodic analysis, not latency-sensitive." },
  ];
}

function Field({
  label,
  hint,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-ink">{label}</span>
      {hint && <span className="mt-0.5 block text-xs text-ink-2">{hint}</span>}
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
        className="input mt-1.5 w-full"
      />
    </label>
  );
}

export function OnboardingWizard({ onClose }: { onClose: () => void }) {
  const { data: state } = useOnboarding();
  const { data: config } = useConfig();
  const update = useUpdateSettings();
  const navigate = useNavigate();
  const startTour = useTour((s) => s.start);

  const [step, setStep] = useState(0);
  const [name, setName] = useState(state?.user_name ?? "");
  const [alpacaKey, setAlpacaKey] = useState("");
  const [alpacaSecret, setAlpacaSecret] = useState("");
  const [alpacaCheck, setAlpacaCheck] = useState<{ ok: boolean; message: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [anthropic, setAnthropic] = useState("");
  const [openai, setOpenai] = useState("");
  const [google, setGoogle] = useState("");
  const [mode, setMode] = useState(state?.system_mode ?? "PAPER_TRADING");
  const [capital, setCapital] = useState(String(state?.initial_capital_usd ?? 100_000));
  const [universe, setUniverse] = useState(config?.universe.us ?? "");
  const [maxPos, setMaxPos] = useState("");
  const [applied, setApplied] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [restart, setRestart] = useState<string[]>([]);

  const saved = config?.keys ?? {};
  // Recommend for the strongest configured provider (same order the CIO uses).
  const provider: Provider | null =
    anthropic.trim() || saved.anthropic ? "claude"
    : openai.trim() || saved.openai ? "openai"
    : google.trim() || saved.google ? "gemini"
    : null;

  const updates = (): Record<string, string> => {
    const u: Record<string, string> = {
      SYSTEM_MODE: mode,
      INITIAL_CAPITAL_USD: capital,
      ONBOARDED: "true",
    };
    const set = (k: string, v: string) => v.trim() && (u[k] = v.trim());
    set("USER_NAME", name);
    set("RISK_MAX_POSITION_PCT", maxPos);
    set("US_SYMBOLS", universe.toUpperCase());
    set("ALPACA_API_KEY", alpacaKey);
    set("ALPACA_API_SECRET", alpacaSecret);
    set("ANTHROPIC_API_KEY", anthropic);
    set("OPENAI_API_KEY", openai);
    set("GOOGLE_API_KEY", google);
    return u;
  };

  const save = (extra: Record<string, string> = {}) =>
    update.mutateAsync({ ...updates(), ...extra }).then((result) => {
      setErrors(result.errors);
      setRestart(result.restart_required);
      if (result.ok) localStorage.setItem("horizon-onboarded", "1");
      return result.ok;
    });

  const applyModels = async () => {
    if (!provider) return;
    const r = REC[provider];
    const ok = await save({
      AI_EXECUTIVE: provider,
      AI_MIDDLE_OFFICE: provider,
      AI_FRONT_OFFICE: provider,
      AI_BACK_OFFICE: provider,
      DEBATE_MODEL: r.debate[0],
    });
    if (!ok) return;
    const res = await runCommand(`model set cio-agent-1 ${provider} ${r.cio[0]}`);
    if (res.error || /rejected/i.test(res.text)) setErrors([res.text]);
    else setApplied(true);
  };

  const check = async () => {
    setChecking(true);
    try {
      setAlpacaCheck(await testAlpaca(alpacaKey.trim(), alpacaSecret.trim()));
    } catch {
      setAlpacaCheck({ ok: false, message: "Could not reach the backend." });
    } finally {
      setChecking(false);
    }
  };

  const next = async () => {
    if (step === 4 && !(await save())) return; // Models -> Done writes everything
    setStep((s) => s + 1);
  };

  const skip = () => {
    // "Skip" still counts as done -- setup is first-launch only; Settings re-runs it.
    update.mutate({ ONBOARDED: "true" });
    localStorage.setItem("horizon-onboarded", "1");
    onClose();
  };

  const finish = (tour: boolean) => {
    onClose();
    navigate("/");
    if (tour) startTour();
  };

  const noAi = !provider;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 p-6 backdrop-blur-sm">
      <div className="w-full max-w-xl overflow-hidden rounded-md border border-line bg-surface shadow-lg">
        <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="grid h-6 w-6 place-items-center rounded bg-accent text-xs font-bold text-accent-ink">
              H
            </span>
            <h2 className="text-sm font-semibold text-ink">Set up Horizon Capital</h2>
          </div>
          <button onClick={skip} className="rounded p-1 text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Skip setup">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-5 py-2">
          {STEPS.map((label, index) => (
            <span
              key={label}
              className={clsx(
                "flex shrink-0 items-center gap-1.5 rounded px-2 py-1 text-2xs font-medium",
                index === step ? "bg-surface-2 text-ink" : "text-ink-3",
              )}
            >
              <span
                className={clsx(
                  "grid h-4 w-4 place-items-center rounded-full text-[9px]",
                  index < step ? "bg-ok text-white" : index === step ? "bg-accent-strong text-accent-ink" : "bg-line text-ink-2",
                )}
              >
                {index < step ? <Check className="h-2.5 w-2.5" /> : index + 1}
              </span>
              {label}
            </span>
          ))}
        </div>

        <div className="space-y-4 px-5 py-5">
          {step === 0 && (
            <>
              <p className="text-sm text-ink-2">
                An AI hedge fund on your machine: strategy agents propose trades, risk and an AI
                debate check them, you stay in control. Two minutes to set up.
              </p>
              <Field label="Your name" hint="Used to greet you in the app." value={name} onChange={setName} placeholder="Ada" />
            </>
          )}

          {step === 1 && (
            <>
              <p className="text-sm text-ink-2">
                Alpaca gives live prices and executes orders. <strong className="text-ink">Paper accounts only</strong> —
                Horizon refuses live-money endpoints by design. Use your paper keys (they start with PK).
                Optional: without them, fills are simulated.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="API key" type="password" value={alpacaKey} onChange={setAlpacaKey} placeholder={saved.alpaca ? `Saved ${saved.alpaca}` : "PK…"} />
                <Field label="Secret" type="password" value={alpacaSecret} onChange={setAlpacaSecret} placeholder={saved.alpaca ? "Saved — leave blank to keep" : ""} />
              </div>
              <div className="flex items-center gap-3">
                <button className="btn" onClick={check} disabled={checking}>
                  {checking ? "Testing…" : "Test connection"}
                </button>
                {alpacaCheck && (
                  <span className={clsx("text-xs", alpacaCheck.ok ? "text-ok" : "text-crit")}>{alpacaCheck.message}</span>
                )}
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <p className="text-sm text-ink-2">
                One key is enough. Skip all three to run rule-based only: debates auto-approve and the
                CIO stays quiet.
              </p>
              <Field label="Anthropic (Claude)" type="password" value={anthropic} onChange={setAnthropic} placeholder={saved.anthropic ? `Saved ${saved.anthropic}` : "sk-ant-…"} />
              <Field label="OpenAI" type="password" value={openai} onChange={setOpenai} placeholder={saved.openai ? `Saved ${saved.openai}` : "sk-…"} />
              <Field label="Google (Gemini)" type="password" value={google} onChange={setGoogle} placeholder={saved.google ? `Saved ${saved.google}` : "AIza…"} />
            </>
          )}

          {step === 3 && (
            <>
              <div className="space-y-2">
                <span className="text-sm font-medium text-ink">Who releases orders?</span>
                {MODES.map((option) => (
                  <button
                    key={option.key}
                    onClick={() => setMode(option.key)}
                    className={clsx(
                      "block w-full rounded border px-3 py-2 text-left transition-colors duration-100",
                      mode === option.key ? "border-accent bg-accent/10" : "border-line hover:bg-surface-2",
                    )}
                  >
                    <span className="text-sm font-medium text-ink">{option.label}</span>
                    <span className="ml-2 text-xs text-ink-2">{option.hint}</span>
                  </button>
                ))}
                {mode === "FULLY_AUTONOMOUS" && noAi && (
                  <p className="text-xs text-crit">No AI key yet — every debate would reject and nothing would trade.</p>
                )}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Starting capital (USD)" hint="Seeds a fresh paper book." value={capital} onChange={setCapital} />
                <Field label="Max position (%)" hint="Largest single holding, % of NAV." value={maxPos} onChange={setMaxPos} placeholder={String(config?.risk.max_position_pct ?? 5)} />
              </div>
              <Field label="US symbols" hint="Comma-separated. Blank keeps the default list." value={universe} onChange={setUniverse} placeholder="SPY,QQQ,AAPL" />
            </>
          )}

          {step === 4 &&
            (provider ? (
              <>
                <p className="text-sm text-ink-2">Recommended for {REC[provider].name}:</p>
                <table className="w-full text-xs">
                  <thead className="text-left text-ink-3">
                    <tr>
                      <th className="pb-1.5 font-medium">Department</th>
                      <th className="pb-1.5 font-medium">Model</th>
                      <th className="pb-1.5 font-medium">Effort</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelRows(provider).map((row) => (
                      <tr key={row.dept} className="border-t border-line align-top">
                        <td className="py-1.5 pr-2">
                          <span className="font-medium text-ink">{row.dept}</span>
                          <span className="block text-ink-3">{row.why}</span>
                        </td>
                        <td className="py-1.5 pr-2 text-ink">{row.model}</td>
                        <td className="py-1.5 text-ink-2">{row.effort}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="flex items-center gap-3">
                  <button className="btn" onClick={applyModels} disabled={update.isPending || applied}>
                    {applied ? <><Check className="h-3.5 w-3.5" /> Applied</> : "Apply recommended"}
                  </button>
                  <span className="text-2xs text-ink-3">
                    Sets the CIO and debate models and routes every department to {REC[provider].name}.
                    Effort is guidance only — the app does not set thinking budgets.
                  </span>
                </div>
              </>
            ) : (
              <p className="text-sm text-ink-2">
                No AI key, so nothing to pick — the agents run rule-based. Add a key in Settings any time.
              </p>
            ))}

          {step === 5 && (
            <>
              <p className="text-sm text-ink">
                You're set{name.trim() ? `, ${name.trim()}` : ""}. Agents start in {MODES.find((m) => m.key === mode)?.label.toLowerCase()} mode.
              </p>
              {restart.length > 0 && (
                <p className="rounded border border-warn/40 bg-warn/15 px-3 py-2 text-xs text-ink">
                  {restart.join(", ")} take effect after an engine restart (title bar → engine).
                </p>
              )}
            </>
          )}

          {errors.length > 0 && <ErrorNote message={errors.join(" · ")} />}
        </div>

        <footer className="flex items-center justify-between border-t border-line px-5 py-3">
          {step < 5 ? (
            <button className="btn btn-ghost" onClick={skip}>
              Skip setup
            </button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            {step > 0 && step < 5 && (
              <button className="btn" onClick={() => setStep((s) => s - 1)}>
                Back
              </button>
            )}
            {step < 5 ? (
              <button className="btn btn-primary" onClick={next} disabled={update.isPending}>
                {step === 4 ? (update.isPending ? "Saving" : "Finish") : "Next"}
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            ) : (
              <>
                <button className="btn" onClick={() => finish(false)}>
                  Go to Overview
                </button>
                <button className="btn btn-primary" onClick={() => finish(true)} autoFocus>
                  Take the tour
                </button>
              </>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}

/** First launch only: shown until setup is finished or skipped (saved as ONBOARDED in .env). */
export function Onboarding() {
  const { data } = useOnboarding();
  // Latch the first answer: saving flips `completed`, and the wizard must stay
  // up long enough to show its Done step.
  const [show, setShow] = useState<boolean | null>(null);
  useEffect(() => {
    if (data && show === null) {
      setShow(!data.completed && localStorage.getItem("horizon-onboarded") !== "1");
    }
  }, [data, show]);

  if (!show) return null;
  return <OnboardingWizard onClose={() => setShow(false)} />;
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token DFB31DFA3EE1 - verify with scripts/authorship.py verify
