// ~/gh/tools/scripts/lint_zsh.ts
//
// Audits the modular Zsh configuration:
//   1. files sourced from ~/.zshrc
//   2. modules in ~/.zsh/
//   3. environment variables expected by ~/.zshrc
//   4. directories on the active PATH
//
// Usage: deno run --allow-read --allow-env lint_zsh.ts
// Exits 1 if any [error] was logged, otherwise 0.

let errorCount = 0;
let warningCount = 0;

function info(message: string): void {
  console.log(`[info] ${message}`);
}

function warn(message: string): void {
  warningCount++;
  console.warn(`[warn] ${message}`);
}

function error(message: string): void {
  errorCount++;
  console.error(`[error] ${message}`);
}

const home = Deno.env.get("HOME") ?? "";
if (home === "") {
  error("HOME is not defined; cannot locate ~/.zshrc or ~/.zsh");
  Deno.exit(1);
}

/** Shortens absolute paths under HOME to ~/... for readable output. */
function displayPath(path: string): string {
  return path === home || path.startsWith(`${home}/`)
    ? `~${path.slice(home.length)}`
    : path;
}

function isNotFound(err: unknown): boolean {
  return err instanceof Deno.errors.NotFound;
}

function describeError(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// ---------------------------------------------------------------------------
// 1. Sourced files in ~/.zshrc
// ---------------------------------------------------------------------------

// Matches `source <path>` or `. <path>` in command position: at the start of
// a line or after a separator (`;`, `&&`, `||`, `|`, `{`, `(`) or a
// `then` / `do` / `else` keyword. The path may be double-quoted,
// single-quoted, or bare.
const sourcePattern =
  /(?:^|[;&|({]|\bthen\b|\bdo\b|\belse\b)\s*(?:source|\.)\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|)]+))/g;

// A file test such as `[[ -f path ]]`, `[ -r path ]`, or `test -e path`.
const fileTestPattern = /(?:\[\[?|\btest)\s+-[efrsL]\s/;

// Loop variables, e.g. `for config_file in ...` or `for config_file (...)`.
const loopVariablePattern = /\bfor\s+(\w+)\s+(?:in\b|\()/g;

// `$name` or `${name}`.
const variableReferencePattern = /\$\{(\w+)\}|\$(\w+)/g;

/**
 * Expands `~`, `$VAR`, and `${VAR}` using the current environment.
 * Returns null if the path still contains unresolved or dynamic parts.
 */
function expandPath(rawPath: string): string | null {
  let expanded = rawPath;
  if (expanded === "~" || expanded.startsWith("~/")) {
    expanded = home + expanded.slice(1);
  }
  expanded = expanded.replace(
    variableReferencePattern,
    (whole, braced?: string, bare?: string) =>
      Deno.env.get(braced ?? bare ?? "") ?? whole,
  );
  return /[$*?`]/.test(expanded) ? null : expanded;
}

function referencedVariables(rawPath: string): string[] {
  return [...rawPath.matchAll(variableReferencePattern)].map(
    (match) => match[1] ?? match[2],
  );
}

async function checkSourcedFile(
  rawPath: string,
  resolvedPath: string,
  isGuarded: boolean,
): Promise<void> {
  try {
    const stats = await Deno.stat(resolvedPath);
    if (stats.isFile) {
      info(`sourced file present: ${displayPath(resolvedPath)}`);
    } else {
      error(`sourced path is not a file: ${displayPath(resolvedPath)}`);
    }
  } catch (err) {
    if (!isNotFound(err)) {
      error(`cannot read sourced file ${rawPath}: ${describeError(err)}`);
    } else if (isGuarded) {
      info(`optional file not present: ${displayPath(resolvedPath)}`);
    } else {
      error(`missing sourced file: ${displayPath(resolvedPath)}`);
    }
  }
}

async function auditSourcedFiles(): Promise<void> {
  const zshrcPath = `${home}/.zshrc`;
  info(`checking files sourced from ${displayPath(zshrcPath)}`);

  let zshrcContent: string;
  try {
    zshrcContent = await Deno.readTextFile(zshrcPath);
  } catch (err) {
    error(`cannot read ${displayPath(zshrcPath)}: ${describeError(err)}`);
    return;
  }

  // Drop whole-line comments before scanning.
  const lines = zshrcContent
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "" && !line.startsWith("#"));

  const loopVariables = new Set(
    [...lines.join("\n").matchAll(loopVariablePattern)].map((m) => m[1]),
  );

  // Tracks open `if` blocks; each entry records whether that branch is
  // guarded by a file test, so `source` lines inside it count as optional.
  const ifGuards: boolean[] = [];
  const checkedPaths = new Set<string>();

  for (const line of lines) {
    const opensIfBlock = /^if\b/.test(line) && !/\bfi\s*;?$/.test(line);
    if (opensIfBlock) {
      ifGuards.push(fileTestPattern.test(line));
    } else if (/^elif\b/.test(line) && ifGuards.length > 0) {
      ifGuards[ifGuards.length - 1] = fileTestPattern.test(line);
    } else if (/^else\b/.test(line) && ifGuards.length > 0) {
      ifGuards[ifGuards.length - 1] = false;
    }
    const insideGuardedBlock = ifGuards.some(Boolean);

    for (const match of line.matchAll(sourcePattern)) {
      const rawPath = match[1] ?? match[2] ?? match[3];

      // Loop variables are covered by the ~/.zsh module audit.
      if (referencedVariables(rawPath).some((name) => loopVariables.has(name))) {
        continue;
      }

      const resolvedPath = expandPath(rawPath);
      if (resolvedPath === null) {
        info(`skipping dynamic source path: ${rawPath}`);
        continue;
      }
      if (checkedPaths.has(resolvedPath)) continue;
      checkedPaths.add(resolvedPath);

      const isGuarded = insideGuardedBlock ||
        fileTestPattern.test(line.slice(0, match.index));
      await checkSourcedFile(rawPath, resolvedPath, isGuarded);
    }

    if (/^fi\b/.test(line)) ifGuards.pop();
  }

  if (checkedPaths.size === 0) {
    info("no statically resolvable source commands found");
  }
}

// ---------------------------------------------------------------------------
// 2. Modules in ~/.zsh/
// ---------------------------------------------------------------------------

async function auditModuleDirectory(): Promise<void> {
  const moduleDir = `${home}/.zsh`;
  info(`checking modules in ${displayPath(moduleDir)}`);

  try {
    const stats = await Deno.stat(moduleDir);
    if (!stats.isDirectory) {
      error(`${displayPath(moduleDir)} exists but is not a directory`);
      return;
    }
  } catch (err) {
    if (isNotFound(err)) {
      error(`module directory not found: ${displayPath(moduleDir)}`);
    } else {
      error(`cannot access ${displayPath(moduleDir)}: ${describeError(err)}`);
    }
    return;
  }

  const moduleNames: string[] = [];
  for await (const entry of Deno.readDir(moduleDir)) {
    if (entry.name.endsWith(".zsh")) moduleNames.push(entry.name);
  }
  moduleNames.sort();

  if (moduleNames.length === 0) {
    warn(`no .zsh modules found in ${displayPath(moduleDir)}`);
    return;
  }

  for (const name of moduleNames) {
    const modulePath = `${moduleDir}/${name}`;
    try {
      // Deno.stat follows symlinks, so linked modules are checked by target.
      const stats = await Deno.stat(modulePath);
      if (!stats.isFile) {
        warn(`module is not a regular file: ${displayPath(modulePath)}`);
        continue;
      }
      const content = await Deno.readTextFile(modulePath);
      if (content.trim() === "") {
        warn(`module is empty: ${displayPath(modulePath)}`);
        continue;
      }
      info(`verified module: ${displayPath(modulePath)}`);
    } catch (err) {
      error(`cannot read module ${displayPath(modulePath)}: ${describeError(err)}`);
    }
  }
}

// ---------------------------------------------------------------------------
// 3. Environment variables
// ---------------------------------------------------------------------------

const requiredVariables = ["HOME", "PATH", "DOTFILES_DIR"];

async function auditEnvironment(): Promise<void> {
  info("checking environment variables");

  for (const name of requiredVariables) {
    if (Deno.env.get(name) === undefined) {
      error(`environment variable not defined: ${name}`);
    }
  }

  const dotfilesDir = Deno.env.get("DOTFILES_DIR");
  if (dotfilesDir === undefined) return;

  try {
    const stats = await Deno.stat(dotfilesDir);
    if (stats.isDirectory) {
      info(`DOTFILES_DIR present: ${displayPath(dotfilesDir)}`);
    } else {
      error(`DOTFILES_DIR is not a directory: ${displayPath(dotfilesDir)}`);
    }
  } catch (err) {
    if (isNotFound(err)) {
      error(`DOTFILES_DIR does not exist: ${displayPath(dotfilesDir)}`);
    } else {
      error(`cannot access DOTFILES_DIR: ${describeError(err)}`);
    }
  }
}

// ---------------------------------------------------------------------------
// 4. PATH directories
// ---------------------------------------------------------------------------

async function auditPath(): Promise<void> {
  info("checking PATH directories");

  const pathEntries = (Deno.env.get("PATH") ?? "").split(":");
  let validCount = 0;

  for (const dir of pathEntries) {
    if (dir === "") {
      warn("empty PATH entry (resolves to the current directory)");
      continue;
    }
    try {
      const stats = await Deno.stat(dir);
      if (stats.isDirectory) {
        validCount++;
      } else {
        warn(`PATH entry is not a directory: ${dir}`);
      }
    } catch (err) {
      if (isNotFound(err)) {
        warn(`PATH entry does not exist: ${dir}`);
      } else {
        error(`cannot access PATH entry ${dir}: ${describeError(err)}`);
      }
    }
  }

  info(`${validCount} of ${pathEntries.length} PATH entries are valid directories`);
}

// ---------------------------------------------------------------------------

await auditSourcedFiles();
await auditModuleDirectory();
await auditEnvironment();
await auditPath();

info(`audit complete: ${errorCount} error(s), ${warningCount} warning(s)`);
Deno.exit(errorCount > 0 ? 1 : 0);
