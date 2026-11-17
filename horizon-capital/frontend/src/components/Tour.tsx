import { useEffect, useLayoutEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { create } from "zustand";

/** Anything can start the tour: onboarding's last step, Settings, etc. */
export const useTour = create<{ open: boolean; start: () => void; stop: () => void }>((set) => ({
  open: false,
  start: () => set({ open: true }),
  stop: () => set({ open: false }),
}));

// Each step spotlights a [data-tour] element; `path` navigates there first.
const STEPS: { target: string; path?: string; title: string; body: string }[] = [
  { target: "nav-/", path: "/", title: "Overview", body: "NAV, P&L and agent health at a glance. Start every session here." },
  { target: "nav-/portfolio", path: "/portfolio", title: "Portfolio", body: "What you hold and your cash, marked to market every 30 seconds." },
  { target: "nav-/trades", path: "/trades", title: "Trading", body: "Orders and fills. In Human approval mode, pending orders wait here for your approve or reject." },
  { target: "nav-/signals", path: "/signals", title: "Signals", body: "What the strategy sleeves want to trade next, before risk and the debate gate." },
  { target: "nav-/debates", path: "/debates", title: "Debates", body: "AI agents argue the strongest signals. Open one to read why a trade was approved or rejected." },
  { target: "nav-/risk", path: "/risk", title: "Risk", body: "Limits, VaR and drawdown. If the kill switch trips, this page tells you why." },
  { target: "controls", title: "Halt and mode", body: "Halt stops every new order instantly. The mode switch picks who releases orders: you or the agents." },
  { target: "nav-/terminal", path: "/terminal", title: "Terminal", body: "The same command line as the terminal app. Type help to see every command." },
  { target: "nav-/settings", path: "/settings", title: "Settings", body: "Keys, trading mode, risk limits and models. Run setup or this tour again from here." },
];

const PAD = 4;
const CARD_W = 280;

export function Tour() {
  const { open, stop } = useTour();
  const navigate = useNavigate();
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const step = STEPS[index];

  useEffect(() => {
    if (open) setIndex(0);
  }, [open]);

  useEffect(() => {
    if (open && step.path) navigate(step.path);
  }, [open, step, navigate]);

  // Measure after navigation settles, and again on resize.
  useLayoutEffect(() => {
    if (!open) return;
    const measure = () =>
      setRect(document.querySelector(`[data-tour="${step.target}"]`)?.getBoundingClientRect() ?? null);
    const frame = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
    };
  }, [open, step]);

  const last = index === STEPS.length - 1;
  const next = () => (last ? stop() : setIndex((i) => i + 1));
  const back = () => setIndex((i) => Math.max(0, i - 1));

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") stop();
      // Enter is left to the focused Next button, so it never double-advances.
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!open) return null;

  // Card sits right of the target; below it when the target is wide (titlebar).
  const below = rect ? rect.width > 240 || rect.right + CARD_W + 16 > window.innerWidth : true;
  const cardStyle = rect
    ? below
      ? { top: rect.bottom + 10, left: Math.min(rect.left, window.innerWidth - CARD_W - 12) }
      : { top: Math.max(8, rect.top - 6), left: rect.right + 12 }
    : { top: "40%", left: "50%", transform: "translateX(-50%)" };

  return (
    <div className="fixed inset-0 z-[110]" role="dialog" aria-modal="true" aria-label="Platform tour">
      {rect ? (
        <div
          className="pointer-events-none fixed rounded-md ring-2 ring-accent transition-all duration-150"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
            boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.45)",
          }}
        />
      ) : (
        <div className="fixed inset-0 bg-black/45" />
      )}
      <div
        className="fixed rounded-md border border-line bg-surface p-4 shadow-lg"
        style={{ width: CARD_W, ...cardStyle }}
      >
        <p className="text-2xs text-ink-3">
          {index + 1} / {STEPS.length}
        </p>
        <h3 className="mt-1 text-sm font-semibold text-ink">{step.title}</h3>
        <p className="mt-1 text-xs text-ink-2">{step.body}</p>
        <div className="mt-3 flex items-center justify-between">
          <button className="btn btn-ghost" onClick={stop}>
            Exit
          </button>
          <div className="flex gap-2">
            {index > 0 && (
              <button className="btn" onClick={back}>
                Back
              </button>
            )}
            <button className="btn btn-primary" onClick={next} autoFocus>
              {last ? "Done" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
