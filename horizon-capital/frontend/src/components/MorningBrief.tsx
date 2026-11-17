import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { ErrorNote, Loading } from "@/components/ui";
import { useBrief, type BriefSegment } from "@/lib/brief-api";
import { clock, timeAgo } from "@/lib/format";

// Rich colour names from services/morning_brief.py → design tokens. Text keeps text
// tokens; the warning line gets a tint instead of low-contrast yellow ink.
const TONE: Record<string, string> = {
  green: "text-up",
  red: "text-down",
  yellow: "rounded-sm bg-warn/15 px-1 text-ink",
  dim: "text-ink-3",
};

const COLLAPSED_KEY = "hc.brief.collapsed";
const VISIT_KEY = "hc.lastVisit";

function store(key: string, value?: string): string | null {
  try {
    if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

// Read once per page load, then stamp now — "since you were last here".
const PREV_VISIT = store(VISIT_KEY);
store(VISIT_KEY, new Date().toISOString());

function Line({ segments }: { segments: BriefSegment[] }) {
  return (
    <li className="leading-5">
      {segments.map(([text, tone], i) => (
        <span key={i} className={tone ? TONE[tone] : undefined}>
          {text}
        </span>
      ))}
    </li>
  );
}

export function MorningBrief() {
  const { data, isLoading, error } = useBrief();
  const [collapsed, setCollapsed] = useState(() => store(COLLAPSED_KEY) === "1");
  const toggle = () => {
    setCollapsed((c) => {
      store(COLLAPSED_KEY, c ? "0" : "1");
      return !c;
    });
  };

  return (
    <section className="card overflow-hidden">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={!collapsed}
        className="flex h-10 w-full items-center justify-between gap-3 px-3 text-left hover:bg-surface-2"
      >
        <span className="flex min-w-0 items-baseline gap-2">
          <h2 className="truncate text-sm font-semibold text-ink">Morning brief</h2>
          <span className="truncate text-xs text-ink-3">
            {PREV_VISIT ? `since your last visit ${timeAgo(PREV_VISIT)}` : "what happened overnight"}
            {data && ` · built ${clock(data.generated_at)}`}
          </span>
        </span>
        <ChevronDown
          className={clsx("h-4 w-4 shrink-0 text-ink-3 transition-transform", collapsed && "-rotate-90")}
          aria-hidden
        />
      </button>
      {!collapsed && (
        <div className="border-t border-line">
          {isLoading ? (
            <Loading label="Building brief" />
          ) : error || !data ? (
            <div className="p-3">
              <ErrorNote message={`GET /api/desktop/brief failed (${(error as Error | null)?.message ?? "no data"})`} />
            </div>
          ) : (
            <div className="grid gap-x-6 gap-y-4 p-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.sections.map((s) => (
                <div key={s.title} className="min-w-0">
                  <h3 className="mb-1 text-2xs font-medium uppercase tracking-wide text-ink-3">{s.title}</h3>
                  <ul className="nums text-sm text-ink">
                    {s.lines.map((line, i) => (
                      <Line key={i} segments={line} />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
