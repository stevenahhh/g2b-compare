import type { LegacyProfileManifest } from "./profile.js";

export type LegacyScalarValue =
  | { readonly kind: "blank" }
  | { readonly kind: "text"; readonly value: string }
  | { readonly kind: "number"; readonly value: string }
  | { readonly kind: "boolean"; readonly value: boolean }
  | { readonly kind: "error"; readonly value: string };

export type LegacyCellValue =
  | LegacyScalarValue
  | {
      readonly kind: "formula";
      readonly untrustedFormula: string;
      readonly cached: LegacyScalarValue;
    };

export type LegacyCellDto = {
  readonly sheet: string;
  readonly address: string;
  readonly value: LegacyCellValue;
};

export type LegacyItemDto = {
  readonly position: number;
  readonly sourceRow: number;
  readonly quoteRow: number | null;
  readonly itemName: string;
  readonly specification: string;
  readonly unit: string;
  readonly cells: readonly LegacyCellDto[];
};

export type LegacyPackageDto = {
  readonly memberCount: number;
  readonly uncompressedBytes: number;
  readonly memberSha256: Readonly<Record<string, string>>;
  readonly specialParts: {
    readonly drawings: number;
    readonly media: number;
    readonly comments: number;
    readonly vml: number;
    readonly activeX: number;
    readonly printerSettings: number;
    readonly externalLinks: number;
  };
};

export type LegacyImportDto = {
  readonly schemaVersion: "legacy-import-v1";
  readonly profileId: LegacyProfileManifest["profileId"];
  readonly profileSlug: string;
  readonly sourceSha256: string;
  readonly capacity: number;
  readonly items: readonly LegacyItemDto[];
  readonly baselineInventory: LegacyProfileManifest["baselineInventory"];
  readonly inheritedWarnings: LegacyProfileManifest["inheritedWarnings"];
  readonly package: LegacyPackageDto;
};
