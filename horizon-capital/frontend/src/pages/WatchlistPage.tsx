// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-037F0BAACD37
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { Check, ListPlus, Minus, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { SymbolChart } from "@/components/charts/SymbolChart";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, Segmented } from "@/components/ui";
import {
  useCatalogCategories,
  useCatalogSearch,
  useQuotes,
  useRecommended,
  useSymbolDetail,
  useSymbolHistory,
  useSymbolSelection,
  useWatchlist,
  useWatchlistChange,
} from "@/hooks/useWatchlist";
import type {
  CatalogRow,
  HistoryRange,
  PricedRow,
  Quote,
  StreamInfo,
  WatchlistChange,
} from "@/hooks/useWatchlist";
import { money, num, pct, timeAgo, tone } from "@/lib/format";

type OpenDetail = (symbol: string) => void;
type OnChange = (result: WatchlistChange) => void;

function useDebounced<T>(value: T, ms = 150): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function Checkbox({ checked, disabled }: { checked: boolean; disabled?: boolean }) {
  return (
    <span
      aria-hidden
      className={clsx(
        "grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors",
        checked ? "border-accent bg-accent text-accent-ink" : "border-line-strong bg-surface",
        disabled && "opacity-40",
      )}
    >
      {checked && <Check className="h-3 w-3" />}
    </span>
  );
}

/** Last price + day change, the same everywhere a company appears. */
function PriceCell({ quote }: { quote?: Quote | null }) {
  return (
    <div className="shrink-0 text-right">
      <div className="nums text-sm text-ink">{quote?.price ? money(quote.price) : "—"}</div>
      <div className={clsx("nums text-xs", tone(quote?.change_pct))}>
        {quote?.prev_close ? pct(quote.change_pct) : "—"}
      </div>
    </div>
  );
}

/** One-click add, or "On list" once it's there. */
function AddButton({ row, onChange }: { row: PricedRow; onChange: OnChange }) {
  const change = useWatchlistChange();
  if (row.on_watchlist) return <Badge tone="good">On list</Badge>;
  // Not in the Alpaca catalog (e.g. a Polymarket pick) is not "untradable" -- just not addable here.
  if (!row.tradable) return row.exchange ? <Badge tone="bad">Not tradable</Badge> : null;
  return (
    <button
      className="btn btn-ghost h-6 px-1.5 text-xs"
      disabled={change.isPending}
      onClick={(e) => {
        e.stopPropagation();
        change.mutate({ action: "add", symbols: [row.symbol] }, { onSuccess: onChange });
      }}
      title={`Add ${row.ticker} to the watchlist`}
    >
      <Plus className="h-3.5 w-3.5" /> Add
    </button>
  );
}

/** Outcome of the last add/remove, including every rejection and why. */
function ChangeSummary({ result, onDismiss }: { result: WatchlistChange; onDismiss: () => void }) {
  const lines: { text: string; className: string }[] = [];
  if (result.added?.length)
    lines.push({ text: `Added ${result.added.join(", ")}`, className: "text-up" });
  if (result.removed?.length)
    lines.push({ text: `Removed ${result.removed.join(", ")}`, className: "text-up" });
  if (result.already?.length)
    lines.push({ text: `Already on the list: ${result.already.join(", ")}`, className: "text-ink-2" });
  for (const r of result.rejected ?? [])
    lines.push({ text: `${r.symbol}: ${r.reason}`, className: "text-down" });
  if (!lines.length) return null;
  return (
    <div className="relative mb-3 rounded-md border border-line bg-surface-2 px-3 py-2 pr-8 text-sm">
      {lines.map((line, i) => (
        <p key={i} className={line.className}>
          {line.text}
        </p>
      ))}
      {(result.added?.length || result.removed?.length) && (
        <p className="mt-0.5 text-xs text-ink-3">
          {result.count} symbols on the watchlist. Live now: feeds re-subscribed, no restart.
        </p>
      )}
      <button
        onClick={onDismiss}
        className="absolute right-2 top-2 rounded p-0.5 text-ink-3 hover:bg-surface hover:text-ink"
        title="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search & browse
// ---------------------------------------------------------------------------

function Finder({ onChange, onOpen }: { onChange: OnChange; onOpen: OpenDetail }) {
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("");
  const [sector, setSector] = useState("");
  const [active, setActive] = useState(0);
  const { selected, toggle, clear } = useSymbolSelection();
  const q = useDebounced(query.trim());
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const categories = useCatalogCategories();
  const search = useCatalogSearch({ q, group, sector });
  const change = useWatchlistChange();

  const rows = useMemo(() => search.data?.pages.flatMap((p) => p.results) ?? [], [search.data]);
  const quotes = useQuotes(rows.map((r) => r.symbol));
  const total = search.data?.pages[0]?.total ?? 0;
  const catalog = categories.data?.catalog;

  useEffect(() => {
    setActive(0);
    listRef.current?.scrollTo({ top: 0 });
  }, [q, group, sector]);

  useEffect(() => {
    listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [active]);

  // Arrowing toward the end of what's loaded pulls the next page in.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = search;
  useEffect(() => {
    if (active >= rows.length - 5 && hasNextPage && !isFetchingNextPage) fetchNextPage();
  }, [active, rows.length, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // "/" jumps to the search box from anywhere on the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName ?? "").toLowerCase();
      if (e.key === "/" && tag !== "input" && tag !== "select" && tag !== "textarea") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const selectable = (row: CatalogRow) => row.tradable && !row.on_watchlist;

  const add = () => {
    if (!selected.size || change.isPending) return;
    change.mutate(
      { action: "add", symbols: [...selected] },
      {
        onSuccess: (result) => {
          onChange(result);
          clear();
        },
      },
    );
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const row = rows[active];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(rows.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) add();
      else if (e.shiftKey && row) onOpen(row.symbol);
      else if (row && selectable(row)) toggle(row.symbol);
    } else if (e.key === "Escape") {
      if (selected.size) clear();
      else setQuery("");
    }
  };

  const groups = [
    { id: "", label: "All", count: catalog?.size ?? 0 },
    ...(categories.data?.groups ?? []),
  ];
  const india = categories.data?.markets.find((m) => m.id === "india");

  return (
    <Card
      title="Add symbols"
      subtitle={
        catalog?.size
          ? `${catalog.size.toLocaleString()} US stocks, ETFs and crypto pairs from Alpaca`
          : "Symbol catalog"
      }
      bodyClassName=""
    >
      <div className="space-y-2 border-b border-line p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" />
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search ticker or company — AAPL, nvidia, bitcoin"
            role="combobox"
            aria-expanded
            aria-controls="catalog-results"
            aria-activedescendant={rows[active] ? `catalog-${rows[active].symbol}` : undefined}
            className="input h-8 w-full pl-8"
          />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {groups.map((g) => (
            <button
              key={g.id || "all"}
              onClick={() => setGroup(g.id)}
              className={clsx(
                "rounded border px-2 py-0.5 text-xs transition-colors",
                group === g.id
                  ? "border-accent/40 bg-accent/10 font-medium text-ink"
                  : "border-line text-ink-2 hover:bg-surface-2 hover:text-ink",
              )}
            >
              {g.label}
              {g.count > 0 && (
                <span className="nums ml-1 text-ink-3">{g.count.toLocaleString()}</span>
              )}
            </button>
          ))}
          {india && !india.available && (
            <span
              className="cursor-not-allowed rounded border border-dashed border-line px-2 py-0.5 text-xs text-ink-3"
              title={india.note}
            >
              India · coming with Zerodha
            </span>
          )}
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="input ml-auto h-6 text-xs"
            aria-label="Sector"
          >
            <option value="">All sectors</option>
            {categories.data?.sectors.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name} ({s.count})
              </option>
            ))}
          </select>
        </div>

        {catalog?.error && (
          <p className="text-xs text-warn">
            {catalog.error}
            {catalog.size ? " — showing the cached catalog." : ""}
          </p>
        )}
      </div>

      {search.isLoading ? (
        <Loading label="Loading catalog" />
      ) : search.isError ? (
        <div className="p-3">
          <ErrorNote message="Search failed — is the backend running?" />
        </div>
      ) : !catalog?.size && !rows.length ? (
        <Empty
          message="No symbol catalog yet"
          hint={catalog?.error ?? "The catalog loads from Alpaca's asset list."}
        />
      ) : !rows.length ? (
        <Empty message={`No matches for "${q}"`} hint="Try a company name or a shorter ticker." />
      ) : (
        <ul
          id="catalog-results"
          ref={listRef}
          role="listbox"
          aria-multiselectable
          className={clsx(
            "max-h-[520px] divide-y divide-line overflow-y-auto",
            search.isPlaceholderData && "opacity-60",
          )}
        >
          {rows.map((row, i) => {
            const checked = selected.has(row.symbol) || row.on_watchlist;
            return (
              <li
                key={row.symbol}
                id={`catalog-${row.symbol}`}
                role="option"
                aria-selected={checked}
                onClick={() => {
                  setActive(i);
                  onOpen(row.symbol);
                }}
                className={clsx(
                  "flex cursor-pointer items-center gap-3 px-3 py-1.5 transition-colors",
                  i === active ? "bg-surface-2" : "hover:bg-surface-2",
                )}
              >
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setActive(i);
                    if (selectable(row)) toggle(row.symbol);
                  }}
                  disabled={!selectable(row)}
                  title={
                    row.on_watchlist
                      ? "Already on your watchlist"
                      : row.tradable
                        ? "Select to add"
                        : "Not tradable on Alpaca"
                  }
                  className="p-0.5"
                >
                  <Checkbox checked={checked} disabled={!selectable(row)} />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium text-ink">{row.ticker}</span>
                    {row.sp500 && <Badge>S&amp;P 500</Badge>}
                    {row.etf && <Badge>ETF</Badge>}
                    {row.asset_class === "crypto" && <Badge tone="accent">Crypto</Badge>}
                    {row.on_watchlist && <Badge tone="good">On list</Badge>}
                    {!row.tradable && <Badge tone="bad">Not tradable</Badge>}
                  </div>
                  <div className="truncate text-xs text-ink-2">
                    {row.name}
                    <span className="text-ink-3">
                      {" "}
                      · {row.exchange}
                      {row.sector ? ` · ${row.sector}` : ""}
                    </span>
                  </div>
                </div>
                <PriceCell quote={quotes.data?.[row.symbol]} />
              </li>
            );
          })}
          {hasNextPage && (
            <li className="px-3 py-2 text-center">
              <button
                className="btn btn-ghost text-xs"
                disabled={isFetchingNextPage}
                onClick={() => fetchNextPage()}
              >
                {isFetchingNextPage ? "Loading" : "Load more"}
              </button>
            </li>
          )}
        </ul>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2">
        <span className="text-xs text-ink-2">
          {selected.size ? (
            <span className="font-medium text-ink">{selected.size} selected</span>
          ) : (
            <span className="nums">
              {rows.length ? `${rows.length.toLocaleString()} of ${total.toLocaleString()}` : ""}
            </span>
          )}
          <span className="ml-2 hidden text-ink-3 lg:inline">
            ↑↓ move · Enter select · Shift+Enter details · Ctrl+Enter add · / search
          </span>
        </span>
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button className="btn btn-ghost" onClick={clear}>
              Clear
            </button>
          )}
          <button className="btn btn-primary" disabled={!selected.size || change.isPending} onClick={add}>
            <ListPlus className="h-3.5 w-3.5" />
            {change.isPending ? "Adding" : `Add${selected.size ? ` ${selected.size}` : ""}`}
          </button>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Recommended
// ---------------------------------------------------------------------------

function PricedList({
  rows,
  onChange,
  onOpen,
  extra,
}: {
  rows: PricedRow[];
  onChange: OnChange;
  onOpen: OpenDetail;
  extra?: (row: PricedRow) => React.ReactNode;
}) {
  return (
    <ul className="divide-y divide-line">
      {rows.map((row) => (
        <li
          key={row.symbol}
          onClick={() => onOpen(row.symbol)}
          className="flex cursor-pointer items-center gap-3 px-3 py-1.5 transition-colors hover:bg-surface-2"
        >
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-ink">{row.ticker}</div>
            <div className="truncate text-xs text-ink-2">{row.name ?? row.symbol}</div>
            {extra?.(row)}
          </div>
          <PriceCell quote={row} />
          <div className="w-16 shrink-0 text-right">
            <AddButton row={row} onChange={onChange} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function RecommendedView({ onChange, onOpen }: { onChange: OnChange; onOpen: OpenDetail }) {
  const { data, isLoading, isError } = useRecommended();
  const [moverTab, setMoverTab] = useState<"gainers" | "losers" | "most_actives">("gainers");

  if (isLoading) return <Loading label="Loading strategy picks and market movers" />;
  if (isError || !data) return <ErrorNote message="Could not load recommendations." />;

  const { strategy, movers, sentiment } = data;
  return (
    <div className="space-y-3">
      <Card
        title="Strategy picks"
        subtitle="What Horizon's strategy is currently holding/targeting — not personal advice"
        bodyClassName=""
      >
        <p className="border-b border-line px-3 py-1.5 text-xs text-ink-3">
          {strategy.source === "live"
            ? "Live from the running strategy agent: portfolio weight, the sleeve that picked it, and its reason."
            : "Engine not running: showing the last target each symbol was given. Sleeve and reason need the live engine."}
        </p>
        {!strategy.picks.length ? (
          <Empty
            message="No targets yet"
            hint="The strategy hasn't produced a signal. Start the engine, or wait for its next rebalance."
          />
        ) : (
          <PricedList
            rows={strategy.picks}
            onChange={onChange}
            onOpen={onOpen}
            extra={(row) => {
              const pick = strategy.picks.find((p) => p.symbol === row.symbol)!;
              return (
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-2xs text-ink-3">
                  <span className="nums font-medium text-ink-2">{(pick.weight * 100).toFixed(1)}%</span>
                  {pick.sleeve && <Badge>{pick.sleeve}</Badge>}
                  {pick.held && <Badge tone="good">Held</Badge>}
                  <span className="truncate">{pick.reason}</span>
                </div>
              );
            }}
          />
        )}
      </Card>

      <Card
        title="Market movers"
        subtitle={`Market activity, not recommendations${movers.filter ? ` · ${movers.filter}` : ""}`}
        action={
          <Segmented
            ariaLabel="Mover list"
            options={[
              { value: "gainers", label: "Gainers" },
              { value: "losers", label: "Losers" },
              { value: "most_actives", label: "Most active" },
            ]}
            value={moverTab}
            onChange={setMoverTab}
          />
        }
        bodyClassName=""
      >
        {movers.error ? (
          <div className="p-3">
            <ErrorNote message={movers.error} />
          </div>
        ) : !movers[moverTab].length ? (
          <Empty message="Nothing here right now" hint="Movers fill in while the market trades." />
        ) : (
          <PricedList rows={movers[moverTab]} onChange={onChange} onOpen={onOpen} />
        )}
        {movers.last_updated && (
          <p className="border-t border-line px-3 py-1.5 text-2xs text-ink-3">
            Alpaca screener · updated {timeAgo(movers.last_updated)}
          </p>
        )}
      </Card>

      {sentiment.length > 0 && (
        <Card
          title="News sentiment on your watchlist"
          subtitle="FinBERT on recent headlines — advisory, unvalidated signal"
          bodyClassName=""
        >
          <PricedList
            rows={sentiment}
            onChange={onChange}
            onOpen={onOpen}
            extra={(row) => {
              const s = sentiment.find((r) => r.symbol === row.symbol)!.sentiment;
              return (
                <div className={clsx("mt-0.5 text-2xs", s.label === "positive" ? "text-up" : "text-down")}>
                  {s.label} {s.score.toFixed(2)}
                </div>
              );
            }}
          />
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Your watchlist
// ---------------------------------------------------------------------------

function StreamNote({ stream }: { stream: StreamInfo }) {
  let text: string;
  let warn = false;
  if (stream.mode === "stream" && stream.limit) {
    warn = true;
    text =
      `Alpaca's free plan streams ${stream.limit} symbols live: ${stream.streaming} of your ` +
      `${stream.us_symbols} US symbols tick in real time, the rest refresh every ${stream.poll_seconds}s.`;
  } else if (stream.mode === "stream") {
    text = `Live ticks on ${stream.streaming} US symbols.`;
    if (stream.us_symbols > stream.free_plan_limit)
      text += ` On Alpaca's free plan only ${stream.free_plan_limit} stream; the rest refresh every ${stream.poll_seconds}s.`;
  } else if (stream.mode === "rest") {
    text = "Alpaca stream unavailable — polling latest trades every 10s.";
  } else {
    text = `Prices refresh every ${stream.poll_seconds}s from Alpaca snapshots.`;
    if (stream.us_symbols > stream.free_plan_limit)
      text += ` Live streaming covers ${stream.free_plan_limit} symbols on Alpaca's free plan.`;
  }
  return <p className={clsx("px-3 py-2 text-xs", warn ? "text-warn" : "text-ink-3")}>{text}</p>;
}

function YourList({ onChange, onOpen }: { onChange: OnChange; onOpen: OpenDetail }) {
  const { data, isLoading, isError } = useWatchlist();
  const change = useWatchlistChange();
  const { selected, toggle, clear, setAll } = useSymbolSelection();
  const [filter, setFilter] = useState("");

  const items = data?.watchlist ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? items.filter((w) => `${w.symbol} ${w.name ?? ""}`.toLowerCase().includes(needle))
    : items;
  const allShownSelected = shown.length > 0 && shown.every((w) => selected.has(w.symbol));

  const remove = (symbols: string[]) =>
    change.mutate(
      { action: "remove", symbols },
      {
        onSuccess: (result) => {
          onChange(result);
          clear();
        },
      },
    );

  return (
    <Card
      title="Your watchlist"
      subtitle={data ? `${data.count} symbols · no limit` : undefined}
      bodyClassName=""
      action={
        selected.size > 0 && (
          <button className="btn text-down" disabled={change.isPending} onClick={() => remove([...selected])}>
            <Trash2 className="h-3.5 w-3.5" /> Remove {selected.size}
          </button>
        )
      }
    >
      {isLoading ? (
        <Loading />
      ) : isError ? (
        <div className="p-3">
          <ErrorNote message="Could not load the watchlist." />
        </div>
      ) : !items.length ? (
        <Empty message="Your watchlist is empty" hint="Search on the left and add symbols." />
      ) : (
        <>
          <div className="flex items-center gap-3 border-b border-line px-3 py-1.5">
            <button
              onClick={() => (allShownSelected ? clear() : setAll(shown.map((w) => w.symbol)))}
              title={allShownSelected ? "Clear selection" : "Select all shown"}
            >
              <Checkbox checked={allShownSelected} />
            </button>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter your list"
              className="min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-ink-3 focus:outline-none"
            />
          </div>
          <ul className="max-h-[520px] divide-y divide-line overflow-y-auto">
            {shown.map((w) => (
              <li
                key={w.symbol}
                onClick={() => onOpen(w.symbol)}
                className="group flex cursor-pointer items-center gap-3 px-3 py-1.5 transition-colors hover:bg-surface-2"
              >
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(w.symbol);
                  }}
                  className="p-0.5"
                  title="Select"
                >
                  <Checkbox checked={selected.has(w.symbol)} />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-ink">{w.ticker}</div>
                  <div className="truncate text-xs text-ink-2">{w.name ?? w.symbol}</div>
                </div>
                <PriceCell quote={w} />
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    remove([w.symbol]);
                  }}
                  disabled={change.isPending}
                  className="rounded p-1 text-ink-3 opacity-0 transition hover:bg-surface hover:text-down focus-visible:opacity-100 group-hover:opacity-100"
                  title={`Remove ${w.ticker}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {data && (
        <div className="border-t border-line">
          <StreamNote stream={data.stream} />
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Detail drawer
// ---------------------------------------------------------------------------

function StatBox({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded border border-line px-2.5 py-1.5">
      <div className="text-2xs uppercase tracking-wide text-ink-3">{label}</div>
      <div className="nums text-sm text-ink">{value}</div>
    </div>
  );
}

function DetailPanel({
  symbol,
  onClose,
  onChange,
}: {
  symbol: string;
  onClose: () => void;
  onChange: OnChange;
}) {
  const [range, setRange] = useState<HistoryRange>("1Y");
  const detail = useSymbolDetail(symbol);
  const history = useSymbolHistory(symbol, range);
  const change = useWatchlistChange();
  const d = detail.data;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggleWatch = () => {
    if (!d) return;
    change.mutate(
      { action: d.on_watchlist ? "remove" : "add", symbols: [d.symbol] },
      { onSuccess: onChange },
    );
  };

  const s = d?.stats;
  const where =
    d && s?.high_52w && s.low_52w && s.high_52w > s.low_52w && d.quote.price
      ? ((d.quote.price - s.low_52w) / (s.high_52w - s.low_52w)) * 100
      : null;

  return (
    <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal aria-label={`${symbol} details`}>
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <aside className="flex h-full w-full max-w-[600px] flex-col overflow-y-auto border-l border-line bg-surface shadow-xl">
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <h2 className="text-base font-semibold text-ink">{d?.ticker ?? symbol}</h2>
              {d?.exchange && <Badge>{d.exchange}</Badge>}
              {d?.sector && <Badge>{d.sector}</Badge>}
              {d?.on_watchlist && <Badge tone="good">On list</Badge>}
            </div>
            <p className="truncate text-sm text-ink-2">{d?.name ?? (detail.isLoading ? "Loading" : "")}</p>
          </div>
          <div className="flex items-center gap-2">
            {d && (d.tradable || d.on_watchlist) && (
              <button
                className={clsx("btn", !d.on_watchlist && "btn-primary")}
                disabled={change.isPending}
                onClick={toggleWatch}
              >
                {d.on_watchlist ? <Minus className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
                {d.on_watchlist ? "Remove" : "Add to watchlist"}
              </button>
            )}
            <button onClick={onClose} className="btn btn-ghost px-1.5" title="Close (Esc)">
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        {detail.isError ? (
          <div className="p-4">
            <ErrorNote message={`Could not load ${symbol}.`} />
          </div>
        ) : !d ? (
          <Loading />
        ) : (
          <div className="space-y-4 p-4">
            <div className="flex items-baseline gap-3">
              <span className="nums text-2xl font-semibold text-ink">
                {d.quote.price ? money(d.quote.price) : "—"}
              </span>
              {d.quote.prev_close > 0 && (
                <span className={clsx("nums text-sm", tone(d.quote.change_pct))}>
                  {pct(d.quote.change_pct)} today
                </span>
              )}
              {!d.tradable && <Badge tone="bad">Not tradable on Alpaca</Badge>}
            </div>

            <SymbolChart
              bars={history.data?.bars ?? []}
              range={range}
              onRangeChange={setRange}
              loading={history.isFetching}
            />
            {history.data?.source && (
              <p className="-mt-2 text-2xs text-ink-3">
                Daily bars, split/dividend adjusted · source {history.data.source}
              </p>
            )}

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <StatBox label="52w low" value={s?.low_52w ? money(s.low_52w) : "—"} />
              <StatBox label="52w high" value={s?.high_52w ? money(s.high_52w) : "—"} />
              <StatBox label="Volume" value={s?.volume ? num(s.volume, s.volume < 1000 ? 2 : 0) : "—"} />
              <StatBox
                label="30d avg vol"
                value={s?.avg_volume_30d ? num(s.avg_volume_30d, s.avg_volume_30d < 1000 ? 2 : 0) : "—"}
              />
            </div>
            {where !== null && (
              <div>
                <div className="mb-1 flex justify-between text-2xs text-ink-3">
                  <span>52-week range</span>
                  <span className="nums">{where.toFixed(0)}% of range</span>
                </div>
                <div className="relative h-1.5 rounded-full bg-surface-2">
                  <span
                    className="absolute top-1/2 h-3 w-1 -translate-y-1/2 rounded bg-accent"
                    style={{ left: `calc(${Math.min(Math.max(where, 0), 100)}% - 2px)` }}
                  />
                </div>
              </div>
            )}

            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">
                News sentiment
              </h3>
              {d.sentiment ? (
                <p className="text-sm text-ink">
                  <Badge
                    tone={
                      d.sentiment.label === "positive"
                        ? "good"
                        : d.sentiment.label === "negative"
                          ? "bad"
                          : "neutral"
                    }
                  >
                    {d.sentiment.label}
                  </Badge>{" "}
                  <span className="nums text-ink-2">{d.sentiment.score.toFixed(2)}</span>
                  <span className="text-xs text-ink-3">
                    {" "}
                    · FinBERT on headlines, advisory · {timeAgo(d.sentiment.timestamp)}
                  </span>
                </p>
              ) : (
                <p className="text-xs text-ink-3">
                  No reading yet. The sentiment agent scores watchlisted symbols every 5 minutes.
                </p>
              )}
            </div>

            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">
                Headlines · last 72h
              </h3>
              {d.news.length ? (
                <ul className="space-y-1">
                  {d.news.map((h, i) => (
                    <li key={i} className="text-sm leading-snug text-ink">
                      {h}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-ink-3">No recent headlines from Alpaca News.</p>
              )}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WatchlistPage() {
  const [tab, setTab] = useState<"browse" | "recommended">("browse");
  const [result, setResult] = useState<WatchlistChange | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const { data } = useWatchlist();

  return (
    <>
      <PageHeader
        title="Watchlist"
        subtitle={
          data?.note ??
          "What you monitor and can trade manually. The strategy picks from the S&P 500 on its own."
        }
        actions={
          <Segmented
            size="md"
            ariaLabel="Watchlist view"
            options={[
              { value: "browse", label: "Search & browse" },
              { value: "recommended", label: "Recommended" },
            ]}
            value={tab}
            onChange={setTab}
          />
        }
      />
      {result && <ChangeSummary result={result} onDismiss={() => setResult(null)} />}
      <div className="grid items-start gap-3 lg:grid-cols-5">
        <div className="lg:col-span-3">
          {tab === "browse" ? (
            <Finder onChange={setResult} onOpen={setDetail} />
          ) : (
            <RecommendedView onChange={setResult} onOpen={setDetail} />
          )}
        </div>
        <div className="lg:col-span-2">
          <YourList onChange={setResult} onOpen={setDetail} />
        </div>
      </div>
      {detail && (
        <DetailPanel symbol={detail} onClose={() => setDetail(null)} onChange={setResult} />
      )}
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 037F0BAACD37 - verify with scripts/authorship.py verify
