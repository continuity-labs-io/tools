// ~/gh/lint_zsh.ts

const zshrcPath = `${Deno.env.get("HOME")}/.zshrc`;
const zshrcContent = await Deno.readTextFile(zshrcPath);

console.log("--- Starting Zsh Configuration Audit ---");

// 1. Check for Sourced Files
// Only matches lines starting with source or . that are not commented out
const sourceRegex = /^\s*(?:source|\.)\s+([~/\w\._-]+)/gm;
let match;
while ((match = sourceRegex.exec(zshrcContent)) !== null) {
  let filePath = match[1].replace("~", Deno.env.get("HOME") || "");
  try {
    const stats = await Deno.stat(filePath);
    if (stats.isFile) {
      console.log(`✅ Sourced file exists: ${match[1]}`);
    }
  } catch {
    console.error(`❌ Missing sourced file: ${match[1]}`);
  }
}

// 2. Validate current PATH
const pathDirs = Deno.env.get("PATH")?.split(":") || [];
console.log("\n--- Validating Active PATH Directories ---");

for (const dir of pathDirs) {
  try {
    const stats = await Deno.stat(dir);
    if (!stats.isDirectory) {
      console.warn(`⚠️ Path entry is not a directory: ${dir}`);
    }
  } catch {
    console.error(`❌ Path entry does not exist: ${dir}`);
  }
}

console.log("\nAudit Complete.");
