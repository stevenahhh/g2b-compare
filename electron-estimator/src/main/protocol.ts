import { readFile, realpath } from "node:fs/promises";
import path from "node:path";
import { protocol } from "electron";

export const APP_ORIGIN = "app://app";
export const APP_URL = `${APP_ORIGIN}/`;
export const APP_CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "font-src 'self'",
  "img-src 'self'",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
  "object-src 'none'"
].join("; ");

const CONTENT_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2"
} as const;

export function registerAppSchemePrivileges(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: "app",
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true
      }
    }
  ]);
}

export async function resolveAppAsset(
  rendererRoot: string,
  requestUrl: string
): Promise<string | null> {
  if (!URL.canParse(requestUrl)) {
    return null;
  }
  const url = new URL(requestUrl);
  if (
    url.protocol !== "app:" ||
    url.hostname !== "app" ||
    url.port !== "" ||
    url.username !== "" ||
    url.password !== ""
  ) {
    return null;
  }
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch (error) {
    if (error instanceof URIError) {
      return null;
    }
    throw error;
  }
  const requested =
    decodedPath === "/" ? "index.html" : decodedPath.replace(/^\/+/u, "");
  if (
    requested.includes("\0") ||
    requested.includes(":") ||
    path.isAbsolute(requested) ||
    requested.split(/[\\/]/u).some((segment) => segment === "..")
  ) {
    return null;
  }
  const extension = path.extname(requested).toLowerCase();
  if (!(extension in CONTENT_TYPES)) {
    return null;
  }
  const canonicalRoot = await realpath(rendererRoot);
  let canonicalAsset: string;
  try {
    canonicalAsset = await realpath(path.resolve(canonicalRoot, requested));
  } catch (error) {
    if (
      error instanceof Error &&
      ["EACCES", "ENOENT", "ENOTDIR"].includes(
        String(Reflect.get(error, "code"))
      )
    ) {
      return null;
    }
    throw error;
  }
  const relative = path.relative(canonicalRoot, canonicalAsset);
  if (
    relative === "" ||
    relative.startsWith("..") ||
    path.isAbsolute(relative)
  ) {
    return null;
  }
  return canonicalAsset;
}

export async function registerAppProtocol(rendererRoot: string): Promise<void> {
  await realpath(rendererRoot);
  protocol.handle("app", async (request) => {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response(null, { status: 405 });
    }
    const asset = await resolveAppAsset(rendererRoot, request.url);
    if (asset === null) {
      return new Response(null, { status: 404 });
    }
    const extension = path.extname(asset).toLowerCase();
    const contentType = Reflect.get(CONTENT_TYPES, extension);
    if (typeof contentType !== "string") {
      return new Response(null, { status: 404 });
    }
    const headers = {
      "cache-control": "no-store",
      "content-security-policy": APP_CSP,
      "content-type": contentType,
      "x-content-type-options": "nosniff"
    };
    if (request.method === "HEAD") {
      return new Response(null, { status: 200, headers });
    }
    const content = await readFile(asset);
    return new Response(new Uint8Array(content), {
      status: 200,
      headers
    });
  });
}
