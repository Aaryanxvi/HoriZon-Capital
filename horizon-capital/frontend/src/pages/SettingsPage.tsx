// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-0CDB29C47848
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { Check, KeyRound, Power, RefreshCw, RotateCcw, Save, Wand2 } from "lucide-react";
import { useState } from "react";

import {
  useCommand,
  useConfig,
  useEngineControl,
  useOverview,
  useUpdateSettings,
} from "@/lib/api";
import { money } from "@/lib/format";
import { OnboardingWizard } from "@/components/Onboarding";
import {
  Badge,
  Card,
  CommandEcho,
  ErrorNote,
  Loading,
  PageHeader,
} from "@/components/ui";

const MODES = [
  {
    key: "PAPER_TRADING",
    label: "Paper trading",
    blurb: "Signals size and fill immediately; the debate gate auto-approves.",
  },
  {
    key: "HUMAN_APPROVAL",
    label: "Human approval",
    blurb: "Every order waits for you on the Trading screen before it reaches the broker.",
  },
  {
    key: "FULLY_AUTONOMOUS",
    label: "Fully autonomous",
    blurb: "The LLM debate gate is binding — no consensus, no order.",
  },
];

const PROVIDERS = ["auto", "claude", "openai", "gemini", "none"];

/** One editable setting: shows the saved value until you change it. */
function EditableRow({
  label,
  envKey,
  value,
  hint,
  type = "text",
  onSave,
  saving,
}: {
  label: string;
  envKey: string;
  value: string;
  hint?: string;
  type?: string;
  onSave: (key: string, value: string) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const dirty = draft !== null && draft !== value;

  return (
    <div className="flex items-center gap-2 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="text-sm text-soft">{label}</div>
        {hint && <div className="text-2xs text-faint">{hint}</div>}
      </div>
      <input
        type={type}
        value={draft ?? value}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && dirty) {
            onSave(envKey, draft!);
            setDraft(null);
          }
        }}
        className="nums w-44 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-right text-sm text-ink"
      />
      <button
        className={clsx("btn px-2", dirty ? "btn-primary" : "invisible")}
        disabled={saving}
        onClick={() => {
          onSave(envKey, draft!);
          setDraft(null);
        }}
        title="Save"
      >
        <Check className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const { data, isLoading } = useConfig();
  const { data: overview } = useOverview();
  const update = useUpdateSettings();
  const engine = useEngineControl();
  const command = useCommand();
  const [echo, setEcho] = useState<{ html: string; text: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [wizard, setWizard] = useState(false);
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({});

  if (isLoading || !data) return <Loading label="Loading configuration" />;

  const save = (key: string, value: string) =>
    update.mutate(
      { [key]: value },
      {
        onSuccess: (result) => {
          setErrors(result.errors);
          setNotice(
            result.restart_required.length
              ? `Saved. ${result.restart_required.join(", ")} needs an engine restart.`
              : `Saved ${result.applied.join(", ") || key}.`,
          );
        },
      },
    );

  const KEY_FIELDS: { label: string; envKey: string; current: string | null }[] = [
    { label: "Anthropic", envKey: "ANTHROPIC_API_KEY", current: data.keys.anthropic },
    { label: "OpenAI", envKey: "OPENAI_API_KEY", current: data.keys.openai },
    { label: "Google", envKey: "GOOGLE_API_KEY", current: data.keys.google },
    { label: "Alpaca key", envKey: "ALPACA_API_KEY", current: data.keys.alpaca },
    { label: "Alpaca secret", envKey: "ALPACA_API_SECRET", current: null },
    { label: "NewsAPI", envKey: "NEWSAPI_API_KEY", current: data.keys.newsapi },
    { label: "Telegram bot token", envKey: "TELEGRAM_BOT_TOKEN", current: data.keys.telegram },
  ];

  return (
    <>
      {wizard && <OnboardingWizard onClose={() => setWizard(false)} />}

      <PageHeader
        title="Settings"
        subtitle="Changes are written to .env and applied live where that is safe"
        actions={
          <>
            <button className="btn" onClick={() => setWizard(true)}>
              <Wand2 className="h-3.5 w-3.5" /> Run setup
            </button>
            <button className="btn" onClick={() => command.mutate("config", {
              onSuccess: (r) => setEcho({ html: r.html, text: r.text }),
            })} disabled={command.isPending}>
              <RotateCcw className="h-3.5 w-3.5" /> Print config
            </button>
          </>
        }
      />

      {notice && (
        <p className="mb-3 rounded-lg border border-up/20 bg-up/5 px-3 py-2 text-sm text-up">
          {notice}
        </p>
      )}
      {errors.length > 0 && (
        <div className="mb-3">
          <ErrorNote message={errors.join(" · ")} />
        </div>
      )}
      {echo && (
        <div className="mb-4">
          <CommandEcho html={echo.html} text={echo.text} onDismiss={() => setEcho(null)} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Trading mode" subtitle="Takes effect on the next signal">
          <div className="space-y-2">
            {MODES.map((mode) => (
              <button
                key={mode.key}
                disabled={update.isPending}
                onClick={() => save("SYSTEM_MODE", mode.key)}
                className={clsx(
                  "block w-full rounded-lg border px-3 py-2.5 text-left transition",
                  data.system_mode === mode.key
                    ? "border-clay bg-clay/5"
                    : "border-line hover:bg-raised",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-ink">{mode.label}</span>
                  {data.system_mode === mode.key && <Badge tone="accent">active</Badge>}
                </div>
                <p className="mt-0.5 text-xs text-soft">{mode.blurb}</p>
              </button>
            ))}
          </div>
        </Card>

        <Card
          title="Engine"
          subtitle={
            overview?.agents_live
              ? `${overview.agents_running}/${overview.agents_total} agents running`
              : "Agents are stopped"
          }
        >
          <div className="flex flex-wrap gap-2">
            <button
              className="btn btn-primary"
              disabled={engine.isPending || Boolean(overview?.agents_running)}
              onClick={() => engine.mutate("start")}
            >
              Start agents
            </button>
            <button
              className="btn"
              disabled={engine.isPending || !overview?.agents_running}
              onClick={() => engine.mutate("restart")}
            >
              <RefreshCw className="h-3.5 w-3.5" /> Restart
            </button>
            <button
              className="btn text-down"
              disabled={engine.isPending || !overview?.agents_running}
              onClick={() => engine.mutate("stop")}
            >
              <Power className="h-3.5 w-3.5" /> Stop
            </button>
          </div>
          <p className="mt-3 text-xs text-soft">
            Restart after changing the universe or starting capital — those are read once when
            an agent starts. Storage stays up either way, so nothing is lost.
          </p>
          <div className="mt-3 border-t border-line pt-3 text-xs text-soft">
            <div className="flex justify-between py-0.5">
              <span>Storage backend</span>
              <span className="nums text-ink">{data.storage_backend}</span>
            </div>
            <div className="flex justify-between py-0.5">
              <span>CIO mode</span>
              <span className="nums text-ink">{data.cio_mode}</span>
            </div>
            <div className="flex justify-between py-0.5">
              <span>Version</span>
              <span className="nums text-ink">{data.version}</span>
            </div>
          </div>
        </Card>

        <Card title="Capital and universe" subtitle="Restart the engine after changing these">
          <EditableRow
            label="Starting capital (USD)"
            hint={`currently ${money(data.initial_capital_usd)}`}
            envKey="INITIAL_CAPITAL_USD"
            value={String(data.initial_capital_usd)}
            onSave={save}
            saving={update.isPending}
          />
          <EditableRow
            label="US symbols"
            envKey="US_SYMBOLS"
            value={data.universe.us}
            onSave={save}
            saving={update.isPending}
          />
          <EditableRow
            label="India symbols"
            envKey="INDIA_SYMBOLS"
            value={data.universe.india}
            onSave={save}
            saving={update.isPending}
          />
          <EditableRow
            label="Crypto symbols"
            envKey="CRYPTO_SYMBOLS"
            value={data.universe.crypto}
            onSave={save}
            saving={update.isPending}
          />
        </Card>

        <Card title="Risk limits" subtitle="Enforced pre-trade by the risk agent">
          <EditableRow
            label="Max drawdown %"
            envKey="RISK_MAX_DRAWDOWN_PCT"
            value={String(data.risk.max_drawdown_pct)}
            onSave={save}
            saving={update.isPending}
          />
          <EditableRow
            label="Max position %"
            envKey="RISK_MAX_POSITION_PCT"
            value={String(data.risk.max_position_pct)}
            onSave={save}
            saving={update.isPending}
          />
          <EditableRow
            label="Max leverage"
            envKey="RISK_MAX_LEVERAGE"
            value={String(data.risk.max_leverage)}
            onSave={save}
            saving={update.isPending}
          />
          <EditableRow
            label="VaR limit %"
            envKey="RISK_VAR_LIMIT_PCT"
            value={String(data.risk.var_limit_pct)}
            onSave={save}
            saving={update.isPending}
          />
          <EditableRow
            label="Risk-free rate"
            hint="decimal, e.g. 0.0425"
            envKey="RISK_FREE_RATE"
            value={String(data.risk.risk_free_rate)}
            onSave={save}
            saving={update.isPending}
          />
        </Card>

        <Card
          title="LLM routing"
          subtitle="Per-department provider; per-agent overrides live in agent_overrides.json"
        >
          <div className="mb-3 flex flex-wrap gap-1.5">
            {data.llm.providers.length ? (
              data.llm.providers.map((provider) => (
                <Badge key={provider} tone="good">
                  {provider}
                </Badge>
              ))
            ) : (
              <Badge tone="warn">no providers configured</Badge>
            )}
          </div>

          {(
            [
              ["Front office", "AI_FRONT_OFFICE", data.llm.front_office],
              ["Middle office", "AI_MIDDLE_OFFICE", data.llm.middle_office],
              ["Back office", "AI_BACK_OFFICE", data.llm.back_office],
              ["Executive", "AI_EXECUTIVE", data.llm.executive],
            ] as const
          ).map(([label, envKey, current]) => (
            <div key={envKey} className="flex items-center justify-between gap-2 py-1.5">
              <span className="text-sm text-soft">{label}</span>
              <select
                value={current}
                disabled={update.isPending}
                onChange={(e) => save(envKey, e.target.value)}
                className="w-36 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink"
              >
                {PROVIDERS.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
            </div>
          ))}

          <button
            className="btn mt-3 w-full"
            disabled={command.isPending}
            onClick={() =>
              command.mutate("models", {
                onSuccess: (r) => setEcho({ html: r.html, text: r.text }),
              })
            }
          >
            Show model assignments
          </button>
        </Card>

        <Card title="API keys" subtitle="Stored in .env; shown masked once saved">
          {KEY_FIELDS.map((field) => (
            <div key={field.envKey} className="flex items-center gap-2 py-1.5">
              <span className="flex min-w-0 flex-1 items-center gap-2 text-sm text-soft">
                <KeyRound className="h-3.5 w-3.5 shrink-0 text-faint" />
                <span className="truncate">{field.label}</span>
                {field.current ? (
                  <span className="nums text-2xs text-faint">{field.current}</span>
                ) : (
                  <Badge>not set</Badge>
                )}
              </span>
              <input
                type="password"
                placeholder="paste to replace"
                value={keyDrafts[field.envKey] ?? ""}
                onChange={(e) =>
                  setKeyDrafts((prev) => ({ ...prev, [field.envKey]: e.target.value }))
                }
                className="w-40 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink"
              />
              <button
                className={clsx(
                  "btn px-2",
                  keyDrafts[field.envKey]?.trim() ? "btn-primary" : "invisible",
                )}
                disabled={update.isPending}
                onClick={() => {
                  save(field.envKey, keyDrafts[field.envKey].trim());
                  setKeyDrafts((prev) => ({ ...prev, [field.envKey]: "" }));
                }}
              >
                <Save className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          <p className="mt-2 text-2xs text-faint">
            New LLM keys register immediately; broker keys apply on the next engine restart.
          </p>
        </Card>

        <Card title="Optional sleeves" subtitle="Toggle them on the Signals screen">
          <div className="flex items-center justify-between py-1.5 text-sm">
            <span className="text-soft">Crypto trend</span>
            <Badge tone={data.sleeves.crypto.enabled ? "good" : "neutral"}>
              {data.sleeves.crypto.enabled
                ? `on · ${(data.sleeves.crypto.weight * 100).toFixed(0)}%`
                : "off"}
            </Badge>
          </div>
          <div className="flex items-center justify-between py-1.5 text-sm">
            <span className="text-soft">Polymarket momentum</span>
            <Badge tone={data.sleeves.polymarket.enabled ? "good" : "neutral"}>
              {data.sleeves.polymarket.enabled
                ? `on · ${(data.sleeves.polymarket.weight * 100).toFixed(0)}%`
                : "off"}
            </Badge>
          </div>
          {data.sleeves.polymarket.markets && (
            <p className="mt-2 break-words text-2xs text-faint">
              {data.sleeves.polymarket.markets}
            </p>
          )}
        </Card>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 0CDB29C47848 - verify with scripts/authorship.py verify
