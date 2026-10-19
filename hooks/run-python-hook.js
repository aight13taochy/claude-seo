#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");

function stripWrappingQuotes(value) {
  return value.replace(/^["']|["']$/g, "");
}

function pythonCandidates() {
  const candidates = [];
  if (process.env.CLAUDE_SEO_PYTHON) {
    candidates.push({
      label: "CLAUDE_SEO_PYTHON",
      exe: stripWrappingQuotes(process.env.CLAUDE_SEO_PYTHON),
      args: [],
    });
  }
  candidates.push(
    { label: "py -3", exe: "py", args: ["-3"] },
    { label: "python3", exe: "python3", args: [] },
    { label: "python", exe: "python", args: [] },
  );
  return candidates;
}

function isStoreStubOutput(text) {
  return /Microsoft Store|WindowsApps|App execution alias|was not found/i.test(text);
}

function probe(candidate) {
  const script = "import sys; print(sys.executable); print(sys.version.split()[0])";
  const result = spawnSync(candidate.exe, [...candidate.args, "-c", script], {
    encoding: "utf8",
  });
  const output = `${result.stdout || ""}\n${result.stderr || ""}`;
  return result.status === 0 && Boolean((result.stdout || "").trim()) && !isStoreStubOutput(output);
}

function main() {
  const [, , hookScript, ...hookArgs] = process.argv;
  if (!hookScript) {
    process.exit(0);
  }

  for (const candidate of pythonCandidates()) {
    if (!probe(candidate)) {
      continue;
    }
    const result = spawnSync(candidate.exe, [...candidate.args, hookScript, ...hookArgs], {
      stdio: "inherit",
    });
    if (result.error && result.error.code === "ENOENT") {
      // The interpreter vanished between probe and run, so the hook never
      // started: trying the next candidate is safe.
      continue;
    }
    if (result.error) {
      // Any other spawn error (EACCES, EPERM, ...) is final. Falling through
      // handed the hook to the next interpreter, so it ran under one that
      // had not been chosen, or a second time if the first spawn had
      // started it before reporting the error.
      console.error(
        `Claude SEO hook could not run ${candidate.label}: ${result.error.message}`,
      );
      process.exit(1);
    }
    process.exit(result.status === null ? 1 : result.status);
  }

  console.error(
    "Claude SEO hook could not find Python. Tried CLAUDE_SEO_PYTHON, py -3, python3, python.",
  );
  process.exit(1);
}

main();
