import clsx from "clsx";
import { ArrowRight, Check, KeyRound, Rocket, SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";

import { useConfig, useOnboarding, useUpdateSettings } from "@/lib/api";
import { ErrorNote } from "@/components/ui";

// Mirrors the terminal's `--setup` wizard: same questions, same .env keys.
const STEPS = ["Trading", "Capital", "Keys"] as const;

const MODES = [
  { key: "PAPER_TRADING", label: "Paper trading", hint: "Simulated fills. Nothing reaches a broker." },
  { key: "HUMAN_APPROVAL", label: "Human approval", hint: "You approve every order before it goes out." },
  { key: "FULLY_AUTONOMOUS", label: "Fully autonomous", hint: "The LLM debate gate decides. Needs an LLM key." },
];

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
      {hint && <span className="mt-0.5 block text-xs text-soft">{hint}</span>}
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint"
      />
    </label>
  );
}

export function OnboardingWizard({ onClose }: { onClose: () => void }) {
  const { data: state } = useOnboarding();
  const { data: config } = useConfig();
  const update = useUpdateSettings();

  const [step, setStep] = useState(0);
  const [mode, setMode] = useState(state?.system_mode ?? "PAPER_TRADING");
  const [capital, setCapital] = useState(String(state?.initial_capital_usd ?? 1_000_000));
  const [universe, setUniverse] = useState(config?.universe.us ?? "");
  const [anthropic, setAnthropic] = useState("");
  const [openai, setOpenai] = useState("");
  const [google, setGoogle] = useState("");
  const [alpacaKey, setAlpacaKey] = useState("");
  const [alpacaSecret, setAlpacaSecret] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [restart, setRestart] = useState<string[]>([]);

  const finish = () => {
    const updates: Record<string, string> = {
      SYSTEM_MODE: mode,
      INITIAL_CAPITAL_USD: capital,
    };
    if (universe.trim()) updates.US_SYMBOLS = universe.trim().toUpperCase();
    if (anthropic.trim()) updates.ANTHROPIC_API_KEY = anthropic.trim();
    if (openai.trim()) updates.OPENAI_API_KEY = openai.trim();
    if (google.trim()) updates.GOOGLE_API_KEY = google.trim();
    if (alpacaKey.trim()) updates.ALPACA_API_KEY = alpacaKey.trim();
    if (alpacaSecret.trim()) updates.ALPACA_API_SECRET = alpacaSecret.trim();

    update.mutate(updates, {
      onSuccess: (result) => {
        setErrors(result.errors);
        setRestart(result.restart_required);
        if (result.ok && result.restart_required.length === 0) {
          localStorage.setItem("horizon-onboarded", "1");
          onClose();
        } else if (result.ok) {
          localStorage.setItem("horizon-onboarded", "1");
        }
      },
    });
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 p-6 backdrop-blur-sm">
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="grid h-6 w-6 place-items-center rounded-md bg-clay text-xs font-bold text-white">
              H
            </span>
            <div>
              <h2 className="text-sm font-semibold text-ink">Set up Horizon Capital</h2>
              <p className="text-2xs text-soft">Saved to .env — the same file the terminal reads</p>
            </div>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-faint hover:bg-raised hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex items-center gap-1 border-b border-line px-5 py-2">
          {STEPS.map((label, index) => (
            <button
              key={label}
              onClick={() => setStep(index)}
              className={clsx(
                "flex items-center gap-1.5 rounded-md px-2 py-1 text-2xs font-medium transition",
                index === step ? "bg-raised text-ink" : "text-faint hover:text-soft",
              )}
            >
              <span
                className={clsx(
                  "grid h-4 w-4 place-items-center rounded-full text-[9px]",
                  index < step ? "bg-up text-white" : index === step ? "bg-clay text-white" : "bg-line text-soft",
                )}
              >
                {index < step ? <Check className="h-2.5 w-2.5" /> : index + 1}
              </span>
              {label}
            </button>
          ))}
        </div>

        <div className="space-y-4 px-5 py-5">
          {step === 0 && (
            <>
              <p className="flex items-center gap-2 text-sm text-soft">
                <SlidersHorizontal className="h-4 w-4 text-clay" />
                How should orders be released?
              </p>
              <div className="space-y-2">
                {MODES.map((option) => (
                  <button
                    key={option.key}
                    onClick={() => setMode(option.key)}
                    className={clsx(
                      "block w-full rounded-lg border px-3 py-2.5 text-left transition",
                      mode === option.key ? "border-clay bg-clay/5" : "border-line hover:bg-raised",
                    )}
                  >
                    <span className="text-sm font-medium text-ink">{option.label}</span>
                    <span className="mt-0.5 block text-xs text-soft">{option.hint}</span>
                  </button>
                ))}
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <Field
                label="Starting capital (USD)"
                hint="Seeds the paper book on a fresh database."
                value={capital}
                onChange={setCapital}
                placeholder="1000000"
              />
              <Field
                label="US universe"
                hint="Comma-separated symbols the sleeves may trade."
                value={universe}
                onChange={setUniverse}
                placeholder="SPY.NYSE,QQQ.NASDAQ,AAPL.NASDAQ"
              />
            </>
          )}

          {step === 2 && (
            <>
              <p className="flex items-center gap-2 text-sm text-soft">
                <KeyRound className="h-4 w-4 text-clay" />
                Optional. Without an LLM key, debates auto-approve and the CIO stays quiet.
              </p>
              <Field label="Anthropic API key" value={anthropic} onChange={setAnthropic} type="password" placeholder="sk-ant-…" />
              <Field label="OpenAI API key" value={openai} onChange={setOpenai} type="password" placeholder="sk-…" />
              <Field label="Google API key" value={google} onChange={setGoogle} type="password" placeholder="AIza…" />
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Alpaca key" value={alpacaKey} onChange={setAlpacaKey} type="password" />
                <Field label="Alpaca secret" value={alpacaSecret} onChange={setAlpacaSecret} type="password" />
              </div>
            </>
          )}

          {errors.length > 0 && <ErrorNote message={errors.join(" · ")} />}
          {restart.length > 0 && (
            <p className="rounded-lg border border-warn/20 bg-warn/5 px-3 py-2 text-xs text-warn">
              Saved. {restart.join(", ")} need an engine restart to take effect — use the engine
              menu in the title bar.
            </p>
          )}
        </div>

        <footer className="flex items-center justify-between border-t border-line px-5 py-3">
          <button className="btn btn-ghost" onClick={onClose}>
            Skip for now
          </button>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button className="btn" onClick={() => setStep((s) => s - 1)}>
                Back
              </button>
            )}
            {step < STEPS.length - 1 ? (
              <button className="btn btn-primary" onClick={() => setStep((s) => s + 1)}>
                Next <ArrowRight className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button className="btn btn-primary" onClick={finish} disabled={update.isPending}>
                <Rocket className="h-3.5 w-3.5" />
                {update.isPending ? "Saving" : "Finish setup"}
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}

/** Shows the wizard on first run, or whenever no LLM key is configured yet. */
export function Onboarding() {
  const { data } = useOnboarding();
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem("horizon-onboarded") === "1",
  );

  if (!data || dismissed || data.completed) return null;
  return <OnboardingWizard onClose={() => setDismissed(true)} />;
}
