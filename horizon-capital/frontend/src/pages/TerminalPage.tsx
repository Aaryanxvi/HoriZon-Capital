// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-A5C9299F3807
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { CornerDownLeft, Eraser } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { useCommandVocabulary } from "@/lib/api";
import { Card, Dot, PageHeader } from "@/components/ui";

interface Line {
  kind: "input" | "output" | "note";
  text?: string;
  html?: string;
}

const QUICK = ["status", "brief", "portfolio", "positions", "risk", "agents", "doctor", "help"];

/**
 * The REPL, not a reimplementation of it: keystrokes go to the same
 * CommandHandler over a websocket, and its Rich output is rendered as-is.
 */
export default function TerminalPage() {
  const [lines, setLines] = useState<Line[]>([
    {
      kind: "note",
      text:
        "Horizon Capital terminal — every command from `python -m app` works here.\n" +
        "Type `help` for the full list. Up/Down for history, Tab to complete.",
    },
  ]);
  const [input, setInput] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { data: vocabulary } = useCommandVocabulary();
  const qc = useQueryClient();
  const navigate = useNavigate();

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${window.location.host}/api/desktop/ws/terminal`);
    socketRef.current = socket;

    socket.onopen = () => setConnected(true);
    socket.onclose = () => {
      setConnected(false);
      setBusy(false);
    };
    socket.onmessage = (message) => {
      const result = JSON.parse(message.data) as {
        text: string;
        html: string;
        action?: string;
      };
      setLines((prev) => [...prev, { kind: "output", html: result.html, text: result.text }]);
      setBusy(false);
      // A command may have changed state (approve, sleeve on, buy) — refresh views.
      qc.invalidateQueries();
      // `dashboard` and `settings` are screens here rather than TUI panels.
      if (result.action === "open_dashboard") navigate("/");
      if (result.action === "open_settings") navigate("/settings");
    };

    return () => socket.close();
  }, [qc, navigate]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  const send = (raw: string) => {
    const command = raw.trim();
    if (!command || !socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;
    setLines((prev) => [...prev, { kind: "input", text: command }]);
    setHistory((prev) => [command, ...prev.filter((c) => c !== command)].slice(0, 100));
    setHistoryIndex(-1);
    setBusy(true);
    socketRef.current.send(command);
    setInput("");
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowUp") {
      event.preventDefault();
      const next = Math.min(historyIndex + 1, history.length - 1);
      if (next >= 0) {
        setHistoryIndex(next);
        setInput(history[next]);
      }
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = historyIndex - 1;
      setHistoryIndex(next);
      setInput(next >= 0 ? history[next] : "");
    } else if (event.key === "Tab") {
      event.preventDefault();
      const matches = (vocabulary?.commands ?? []).filter((c) => c.startsWith(input));
      if (matches.length === 1) {
        setInput(matches[0] + " ");
      } else if (matches.length > 1) {
        setLines((prev) => [...prev, { kind: "note", text: matches.join("   ") }]);
      }
    } else if (event.key === "l" && event.ctrlKey) {
      event.preventDefault();
      setLines([]);
    }
  };

  return (
    <>
      {/* No subtitle: header + frame must fit the 7.5rem budget; connection state lives in the toolbar. */}
      <PageHeader
        title="Terminal"
        actions={
          <button className="btn" onClick={() => setLines([])}>
            <Eraser className="h-3.5 w-3.5" /> Clear
          </button>
        }
      />

      <Card
        className="flex h-[calc(100vh-7.5rem)] flex-col"
        bodyClassName="flex min-h-0 flex-1 flex-col"
      >
        <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-2">
          {QUICK.map((command) => (
            <button
              key={command}
              onClick={() => send(command)}
              disabled={busy || !connected}
              className="h-6 rounded border border-line px-1.5 font-mono text-2xs text-ink-2 transition-colors duration-100 hover:bg-surface-2 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
            >
              {command}
            </button>
          ))}
          <span className="ml-auto inline-flex items-center gap-1.5 text-2xs text-ink-3">
            <Dot tone={connected ? "ok" : "warning"} pulse={!connected} />
            {connected
              ? "Connected to the running engine — same commands, same output as the CLI"
              : "Reconnecting…"}
          </span>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2">
          {lines.map((line, i) => {
            if (line.kind === "input")
              return (
                <div key={i} className="mt-2 font-mono text-xs text-accent-strong">
                  <span className="select-none text-ink-3">horizon&gt; </span>
                  {line.text}
                </div>
              );
            if (line.kind === "note")
              return (
                <pre
                  key={i}
                  className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-ink-3"
                >
                  {line.text}
                </pre>
              );
            return (
              <div
                key={i}
                className="rich-output font-mono text-xs leading-relaxed text-ink"
                dangerouslySetInnerHTML={{ __html: line.html ?? "" }}
              />
            );
          })}
          {busy && <div className="mt-2 font-mono text-xs text-ink-3">working…</div>}
          <div ref={bottomRef} />
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            send(input);
          }}
          className="flex items-center gap-2 border-t border-line bg-surface-2 px-3 py-1.5"
        >
          <span className="select-none font-mono text-xs text-ink-3">horizon&gt;</span>
          <input
            ref={inputRef}
            autoFocus
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={onKeyDown}
            spellCheck={false}
            disabled={!connected}
            placeholder={connected ? "" : "disconnected"}
            aria-label="Command"
            className="flex-1 bg-transparent font-mono text-xs text-ink caret-accent-strong outline-none placeholder:text-ink-3"
          />
          <button
            type="submit"
            className="btn btn-ghost"
            aria-label="Run command"
            disabled={busy || !connected}
          >
            <CornerDownLeft className="h-3.5 w-3.5" />
          </button>
        </form>
      </Card>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token A5C9299F3807 - verify with scripts/authorship.py verify
