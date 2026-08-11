import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

type JsonObject = Record<string, unknown>;

const desktopRoot = resolve(process.cwd());
const tauriRoot = join(desktopRoot, "src-tauri");
const configPath = join(tauriRoot, "tauri.conf.json");
const capabilityPath = join(tauriRoot, "capabilities", "main.json");
const config = JSON.parse(readFileSync(configPath, "utf8")) as JsonObject;
const bundle = config.bundle as JsonObject;
const security = (config.app as JsonObject).security as JsonObject;
const capability = JSON.parse(
  readFileSync(capabilityPath, "utf8"),
) as JsonObject;
const plugins = (config.plugins ?? {}) as JsonObject;
const updater = (plugins.updater ?? {}) as JsonObject;

const nsis = ((bundle.windows as JsonObject | undefined)?.nsis ??
  {}) as JsonObject;

const frontendFiles = [
  ...filesUnder(join(desktopRoot, "dist")),
  ...filesUnder(join(desktopRoot, "src")),
];

function filesUnder(directory: string): string[] {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

describe("Tauri 2 Windows packaging contract", () => {
  it("enables a per-user Windows NSIS installer", () => {
    expect(config.$schema).toBe("https://schema.tauri.app/config/2");
    expect(bundle.active).toBe(true);
    expect(bundle.targets).toContain("nsis");
    expect(nsis.installMode).toBe("currentUser");
  });

  it("bundles only the generated compressed seed resource", () => {
    expect(bundle.resources).toEqual(["resources/seed.sqlite3.zip"]);
    const tauriScript = readFileSync(
      join(desktopRoot, "scripts", "tauri.ps1"),
      "utf8",
    );
    expect(tauriScript).toContain("seed.sqlite3");
    expect(tauriScript).toContain("seedHashPath");
    expect(tauriScript).toContain(
      "FileShare]::ReadWrite -bor [IO.FileShare]::Delete",
    );
    expect(tauriScript).toContain("Publish-Atomically");
    expect(tauriScript).toContain("Get-StreamSha256");
    expect(tauriScript).toContain("entryDigest.Hash -ceq $SourceHash");
    expect(tauriScript).toContain('$env:GITHUB_ACTIONS -ne "true"');
  });

  it("keeps the CSP and Windows capability least-privilege", () => {
    const csp = String(security.csp);
    expect(csp).not.toMatch(/\*|unsafe-eval|https?:\/\/(?!ipc\.localhost)/u);
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("connect-src ipc: http://ipc.localhost");
    expect(csp).toContain("object-src 'none'");

    expect(security.capabilities).toEqual(["main"]);
    expect(capability.platforms).toEqual(["windows"]);
    expect(capability.windows).toEqual(["main"]);
    expect(capability.permissions).toEqual([
      "core:default",
      "updater:default",
      "process:allow-restart",
    ]);
    expect(capability.permissions).not.toEqual(
      expect.arrayContaining([
        expect.stringMatching(/shell|fs|sql|http|global-shortcut/u),
      ]),
    );
  });

  it("publishes only signed GitHub updates while keeping durable data outside the install", () => {
    expect(bundle.createUpdaterArtifacts).toBe(true);
    expect(updater.endpoints).toEqual([
      "https://github.com/stevenahhh/g2b-compare-releases/releases/latest/download/latest.json",
    ]);
    expect(String(updater.pubkey)).toMatch(/^[A-Za-z0-9+/=]{100,}$/u);
    expect((updater.windows as JsonObject).installMode).toBe("passive");
    expect(capability.permissions).toEqual([
      "core:default",
      "updater:default",
      "process:allow-restart",
    ]);

    const runtime = readFileSync(join(tauriRoot, "src", "lib.rs"), "utf8");
    expect(runtime).toContain("app.path().app_data_dir()");
    expect(runtime).toContain('app_data.join("g2b.sqlite3")');
    expect(runtime).not.toContain("BaseDirectory::Executable");
  });

  it("creates draft GitHub Releases only from explicit version tags", () => {
    const workflow = readFileSync(
      resolve(desktopRoot, "..", ".github", "workflows", "release-tauri.yml"),
      "utf8",
    );
    expect(workflow).toContain("tags:");
    expect(workflow).toMatch(/- ["']app-v\*["']/u);
    expect(workflow).toContain("tauri-apps/tauri-action@v1");
    expect(workflow).toContain("owner: stevenahhh");
    expect(workflow).toContain("repo: g2b-compare-releases");
    expect(workflow).toContain(
      "GITHUB_TOKEN: ${{ secrets.RELEASE_REPO_TOKEN }}",
    );
    expect(workflow).toContain("uploadUpdaterJson: true");
    expect(workflow).toContain("updaterJsonPreferNsis: true");
    expect(workflow).toContain("[IO.Compression.ZipFile]::OpenRead");
    expect(workflow).toContain("Entries.Count -ne 1");
    expect(workflow).toContain("ExtractToDirectory");
    expect(workflow).toContain("$extractedHash -cne $sourceHash");
    expect(workflow).toContain("TAURI_SIGNING_PRIVATE_KEY");
    expect(workflow).toContain("TAURI_SIGNING_PRIVATE_KEY_PASSWORD");
    expect(workflow).toContain("G2B_SERVICE_KEY");
    expect(workflow).toContain("releaseDraft: true");
  });

  it("requires the service key for release builds and never falls back silently", () => {
    const buildScript = readFileSync(join(tauriRoot, "build.rs"), "utf8");
    expect(buildScript).toMatch(/PROFILE/u);
    expect(buildScript).toMatch(/profile\s*==\s*["']release["']/u);
    expect(buildScript).toMatch(/G2B_SERVICE_KEY/u);
    expect(buildScript).toMatch(/seed\.sqlite3\.zip\.sha256/u);
    expect(buildScript).toMatch(/rerun-if-changed/u);
    expect(buildScript).toMatch(/EMBEDDED_SEED_SHA256/u);
    expect(buildScript).toMatch(/required for release builds/u);
    const releaseStart = buildScript.indexOf('None if profile == "release"');
    const debugFallback = buildScript.indexOf("None => DEBUG_KEY");
    expect(releaseStart).toBeGreaterThanOrEqual(0);
    expect(debugFallback).toBeGreaterThan(releaseStart);
    expect(buildScript.slice(releaseStart, debugFallback)).toMatch(
      /return Err/u,
    );
  });

  it("publishes stable identity and includes the required Windows icon resource", () => {
    expect(config.productName).toBe("G2B Compare Desktop");
    expect(config.version).toMatch(/^\d+\.\d+\.\d+$/u);
    expect(config.identifier).toBe("kr.co.g2bcompare.desktop");
    expect(config.identifier).not.toMatch(/electron|web|legacy/iu);

    const icons = bundle.icon;
    expect(icons).toEqual(["../../KakaoTalk_20260804_113126254.png"]);
    expect(existsSync(resolve(tauriRoot, String((icons as string[])[0])))).toBe(
      true,
    );
    expect(existsSync(join(tauriRoot, "icons", "icon.ico"))).toBe(true);

    const app = readFileSync(join(desktopRoot, "src", "App.svelte"), "utf8");
    const header = readFileSync(
      join(desktopRoot, "src", "lib", "components", "AppHeader.svelte"),
      "utf8",
    );
    expect(app).toContain('from "../../KakaoTalk_20260804_113126254.png"');
    expect(app).toContain('rel="icon" type="image/png" href={brandIcon}');
    expect(header).toContain(
      'from "../../../../KakaoTalk_20260804_113126254.png"',
    );
  });

  it("contains no plaintext service key in frontend source or dist", () => {
    const forbidden = [
      /G2B_SERVICE_KEY\s*[:=]/u,
      /(?:api|service)[_-]?key\s*[:=]\s*["'][^"']{12,}["']/iu,
      /Bearer\s+[A-Za-z0-9._~-]{20,}/u,
    ];
    for (const file of frontendFiles) {
      const contents = readFileSync(file, "utf8");
      for (const pattern of forbidden) {
        expect(contents, `${file} matches ${pattern}`).not.toMatch(pattern);
      }
    }
  });
});
