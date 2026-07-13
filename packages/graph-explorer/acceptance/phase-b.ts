import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

interface Finding {
  file: string;
  rule: string;
}

const packageRoot = resolve(process.cwd());
const repositoryRoot = resolve(packageRoot, "../..");
const sourceRoots = [
  resolve(repositoryRoot, "packages/graphology-adapter/src"),
  resolve(repositoryRoot, "packages/graph-explorer/src"),
];

const forbidden: Array<[string, RegExp]> = [
  ["runtime fetch", /\bfetch\s*\(/],
  ["XMLHttpRequest", /\bXMLHttpRequest\b/],
  ["WebSocket", /\bWebSocket\b/],
  ["EventSource", /\bEventSource\b/],
  ["sendBeacon", /\bsendBeacon\s*\(/],
  ["localStorage", /\blocalStorage\b/],
  ["sessionStorage", /\bsessionStorage\b/],
  ["indexedDB", /\bindexedDB\b/],
  ["document.cookie", /\bdocument\.cookie\b/],
  ["eval", /\beval\s*\(/],
  ["Function constructor", /\bnew\s+Function\b/],
];

function files(root: string): string[] {
  const result: string[] = [];
  for (const entry of readdirSync(root)) {
    const path = join(root, entry);
    const stats = statSync(path);
    if (stats.isDirectory()) result.push(...files(path));
    else if (path.endsWith(".ts")) result.push(path);
  }
  return result.sort();
}

const findings: Finding[] = [];
for (const root of sourceRoots) {
  for (const file of files(root)) {
    const content = readFileSync(file, "utf8");
    for (const [rule, pattern] of forbidden) {
      if (pattern.test(content)) findings.push({ file: relative(repositoryRoot, file), rule });
    }
  }
}

const packageJson = JSON.parse(
  readFileSync(resolve(packageRoot, "package.json"), "utf8"),
) as { dependencies?: Record<string, string> };
const dependencyNames = Object.keys(packageJson.dependencies ?? {}).sort();
const allowedDependencies = ["graphology", "sigma"];
if (JSON.stringify(dependencyNames) !== JSON.stringify(allowedDependencies)) {
  findings.push({ file: "packages/graph-explorer/package.json", rule: "unexpected runtime dependency" });
}

if (findings.length > 0) {
  console.error(JSON.stringify({ schemaVersion: "knowledge-os-phase-b-scan/v1", findings }, null, 2));
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({
    schemaVersion: "knowledge-os-phase-b-scan/v1",
    scannedRoots: sourceRoots.map((root) => relative(repositoryRoot, root)),
    runtimeDependencies: dependencyNames,
    findings: [],
    readOnly: true,
  }, null, 2));
}
