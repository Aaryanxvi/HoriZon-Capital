const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

let backendProcess = null;

/**
 * Locate the bundled Python backend executable.
 * In development: runs `python desktop_entry.py` from the backend dir.
 * In production: runs the PyInstaller-bundled exe from resources.
 */
function findBackendPath() {
  // Production: look in app resources
  const resourcesPath = process.resourcesPath;
  if (resourcesPath) {
    const bundledExe = path.join(resourcesPath, "backend", "desktop_entry.exe");
    if (fs.existsSync(bundledExe)) return { exe: bundledExe, args: [], cwd: path.dirname(bundledExe) };

    const bundledBin = path.join(resourcesPath, "backend", "desktop_entry");
    if (fs.existsSync(bundledBin)) return { exe: bundledBin, args: [], cwd: path.dirname(bundledBin) };
  }

  // Development: run via Python
  const backendDir = path.join(__dirname, "..", "backend");
  const entryScript = path.join(backendDir, "desktop_entry.py");
  return { exe: "python", args: [entryScript], cwd: backendDir };
}

/**
 * Spawn the backend process and wait for the READY:<port> signal.
 * Resolves with the port number.
 */
function spawnBackend() {
  return new Promise((resolve, reject) => {
    const { exe, args, cwd } = findBackendPath();
    console.log(`[backend] Starting: ${exe} ${args.join(" ")}`);

    backendProcess = spawn(exe, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        STORAGE_BACKEND: "LOCAL",
      },
    });

    let resolved = false;
    const timeout = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        reject(new Error("Backend startup timed out after 30s"));
        killBackend();
      }
    }, 30_000);

    backendProcess.stdout.on("data", (data) => {
      const text = data.toString();
      console.log(`[backend] ${text.trim()}`);

      if (!resolved) {
        const match = text.match(/READY:(\d+)/);
        if (match) {
          resolved = true;
          clearTimeout(timeout);
          resolve(parseInt(match[1], 10));
        }
      }
    });

    backendProcess.stderr.on("data", (data) => {
      console.error(`[backend:err] ${data.toString().trim()}`);
    });

    backendProcess.on("error", (err) => {
      console.error("[backend] Process error:", err);
      if (!resolved) {
        resolved = true;
        clearTimeout(timeout);
        reject(err);
      }
    });

    backendProcess.on("exit", (code) => {
      console.log(`[backend] Exited with code ${code}`);
      backendProcess = null;
    });
  });
}

function killBackend() {
  if (backendProcess) {
    console.log("[backend] Killing backend process...");
    backendProcess.kill("SIGTERM");
    // Force kill after 5s
    setTimeout(() => {
      if (backendProcess) {
        backendProcess.kill("SIGKILL");
      }
    }, 5_000);
  }
}

module.exports = { spawnBackend, killBackend };
