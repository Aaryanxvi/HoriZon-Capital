const { spawn, spawnSync, execFile } = require("child_process");
const path = require("path");
const fs = require("fs");

let backendProcess = null;
const logTail = [];

/** Keep the last lines of backend output so a crash can be explained to the user. */
function remember(line) {
  logTail.push(line);
  if (logTail.length > 200) logTail.shift();
}

function recentLog() {
  return logTail.slice(-25).join("\n");
}

/**
 * Pick the Python that actually has the backend's dependencies.
 * Windows ships a `python` shim that may be a different (older) interpreter than
 * the one the project was installed into, so the launcher is tried first.
 */
function findPython() {
  if (process.env.HORIZON_PYTHON) return { exe: process.env.HORIZON_PYTHON, prefix: [] };

  const candidates =
    process.platform === "win32"
      ? [
          { exe: "py", prefix: ["-3.14"] },
          { exe: "py", prefix: ["-3"] },
          { exe: "python", prefix: [] },
        ]
      : [
          { exe: "python3", prefix: [] },
          { exe: "python", prefix: [] },
        ];

  for (const candidate of candidates) {
    try {
      const probe = spawnSync(candidate.exe, [...candidate.prefix, "-c", "import uvicorn"], {
        stdio: "ignore",
        timeout: 20_000,
      });
      if (probe.status === 0) return candidate;
    } catch {
      /* try the next candidate */
    }
  }
  return { exe: "python", prefix: [] };
}

/**
 * Locate the backend entry point.
 * Production: the PyInstaller bundle in app resources.
 * Development: `<python> backend/desktop_entry.py`.
 */
function findBackendPath() {
  const resourcesPath = process.resourcesPath;
  if (resourcesPath) {
    // PyInstaller onedir puts the exe one level deeper than the copied folder,
    // so check both layouts rather than silently falling back to dev Python.
    const candidates = [
      path.join(resourcesPath, "backend", "desktop_entry.exe"),
      path.join(resourcesPath, "backend", "desktop_entry"),
      path.join(resourcesPath, "backend", "desktop_entry", "desktop_entry.exe"),
      path.join(resourcesPath, "backend", "desktop_entry", "desktop_entry"),
    ];
    for (const bundled of candidates) {
      if (fs.existsSync(bundled) && fs.statSync(bundled).isFile()) {
        return { exe: bundled, args: [], cwd: path.dirname(bundled) };
      }
    }
  }

  const backendDir = path.join(__dirname, "..", "backend");
  const entryScript = path.join(backendDir, "desktop_entry.py");
  const python = findPython();
  return { exe: python.exe, args: [...python.prefix, entryScript], cwd: backendDir };
}

/**
 * Start the backend and resolve with the port it reports.
 * Rejects with the tail of its output so the failure dialog can say what broke.
 */
function spawnBackend() {
  return new Promise((resolve, reject) => {
    const { exe, args, cwd } = findBackendPath();
    console.log(`[backend] starting: ${exe} ${args.join(" ")}`);

    // In a packaged app the built UI sits beside the backend in resources/,
    // not at ../frontend/dist — tell the server where to find it.
    const bundledFrontend = process.resourcesPath
      ? path.join(process.resourcesPath, "frontend")
      : null;

    backendProcess = spawn(exe, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        STORAGE_BACKEND: process.env.STORAGE_BACKEND || "LOCAL",
        HORIZON_RUN_AGENTS: "1",
        PYTHONUNBUFFERED: "1",
        PYTHONIOENCODING: "utf-8",
        ...(bundledFrontend && fs.existsSync(path.join(bundledFrontend, "index.html"))
          ? { HORIZON_FRONTEND_DIST: bundledFrontend }
          : {}),
      },
    });

    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      fn(value);
    };

    // Booting includes SQLite migration and the first agent start; 90s is
    // generous for a cold start on a slow disk but still fails eventually.
    const timeout = setTimeout(() => {
      finish(
        reject,
        new Error(`Backend did not report ready within 90s.\n\n${recentLog()}`),
      );
      killBackend();
    }, 90_000);

    backendProcess.stdout.on("data", (data) => {
      const text = data.toString();
      text.split(/\r?\n/).filter(Boolean).forEach(remember);
      console.log(`[backend] ${text.trim()}`);
      const match = text.match(/READY:(\d+)/);
      if (match) finish(resolve, parseInt(match[1], 10));
    });

    backendProcess.stderr.on("data", (data) => {
      const text = data.toString();
      text.split(/\r?\n/).filter(Boolean).forEach(remember);
      console.error(`[backend:err] ${text.trim()}`);
    });

    backendProcess.on("error", (err) => {
      finish(reject, new Error(`Could not launch the backend (${exe}): ${err.message}`));
    });

    backendProcess.on("exit", (code) => {
      console.log(`[backend] exited with code ${code}`);
      backendProcess = null;
      finish(
        reject,
        new Error(`Backend exited with code ${code} before it was ready.\n\n${recentLog()}`),
      );
    });
  });
}

function killBackend() {
  if (!backendProcess) return;
  const { pid } = backendProcess;
  console.log("[backend] stopping…");

  if (process.platform === "win32") {
    // The child is a launcher that spawns the real interpreter; SIGTERM to the
    // launcher alone leaves uvicorn holding the port.
    execFile("taskkill", ["/pid", String(pid), "/T", "/F"], () => {});
  } else {
    backendProcess.kill("SIGTERM");
    setTimeout(() => backendProcess?.kill("SIGKILL"), 5_000);
  }
  backendProcess = null;
}

module.exports = { spawnBackend, killBackend, recentLog };
