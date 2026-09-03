import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const HTTP_METHODS = new Set(["get", "post", "put", "patch", "delete", "options", "head"]);

function normalizePath(path) {
  return path
    .replace(/:([A-Za-z_][A-Za-z0-9_]*)/g, "{$1}")
    .replace(/\/$/, "") || "/";
}

function extractJavaScriptRoutes(source, receiver, prefix = "") {
  const routes = new Set();
  const pattern = new RegExp(`\\b${receiver}\\.(get|post|put|patch|delete)\\(\\s*["']([^"']+)["']`, "g");
  for (const match of source.matchAll(pattern)) {
    const suffix = match[2] === "/" ? "" : match[2];
    routes.add(`${match[1].toUpperCase()} ${normalizePath(`${prefix}${suffix}`)}`);
  }
  return routes;
}

function extractPythonRoutes(source, receiver, prefix = "") {
  const routes = new Set();
  const pattern = new RegExp(`@${receiver}\\.(get|post|put|patch|delete)\\(\\s*["']([^"']+)["']`, "g");
  for (const match of source.matchAll(pattern)) {
    routes.add(`${match[1].toUpperCase()} ${normalizePath(`${prefix}${match[2]}`)}`);
  }
  return routes;
}

function extractOpenApiOperations(source) {
  const operations = new Set();
  let currentPath = "";
  for (const line of source.split(/\r?\n/)) {
    const pathMatch = /^  (\/[^:]*?(?:\{[^}]+\}[^:]*)?):\s*$/.exec(line);
    if (pathMatch) {
      currentPath = pathMatch[1];
      continue;
    }
    const methodMatch = /^    ([a-z]+):\s*$/.exec(line);
    if (currentPath && methodMatch && HTTP_METHODS.has(methodMatch[1])) {
      operations.add(`${methodMatch[1].toUpperCase()} ${normalizePath(currentPath)}`);
    }
  }
  return operations;
}

test("OpenAPI contains every implemented Express and FastAPI operation", async () => {
  const [server, auth, blogs, memory, engine, sector, openapi] = await Promise.all([
    readFile(join(root, "server.mjs"), "utf8"),
    readFile(join(root, "lib", "auth.mjs"), "utf8"),
    readFile(join(root, "lib", "blogs-router.mjs"), "utf8"),
    readFile(join(root, "lib", "memory-router.mjs"), "utf8"),
    readFile(join(root, "engine", "app", "main.py"), "utf8"),
    readFile(join(root, "engine", "sector", "api.py"), "utf8"),
    readFile(join(root, "openapi.yaml"), "utf8"),
  ]);

  const implemented = new Set([
    ...extractJavaScriptRoutes(server, "app"),
    ...extractJavaScriptRoutes(auth, "app"),
    ...extractJavaScriptRoutes(blogs, "router", "/api/blogs"),
    ...extractJavaScriptRoutes(memory, "app"),
    ...extractPythonRoutes(engine, "app"),
    ...extractPythonRoutes(sector, "router", "/v1/sector"),
  ]);
  const contracted = extractOpenApiOperations(openapi);
  const missing = [...implemented].filter((operation) => !contracted.has(operation)).sort();

  assert.deepEqual(
    missing,
    [],
    `OpenAPI is missing implemented operations:\n${missing.map((item) => `- ${item}`).join("\n")}`,
  );
});

test("BlogPreview contracts the optional publication timestamp", async () => {
  const openapi = await readFile(join(root, "openapi.yaml"), "utf8");
  const schema = openapi.match(/    BlogPreview:\n([\s\S]*?)\n    BlogJobStart:/)?.[1] || "";
  assert.match(schema, /publishedAt:\n\s+type: string\n\s+format: date-time/);
});
