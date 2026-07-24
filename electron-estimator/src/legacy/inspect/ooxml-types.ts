export type ResolvedSheet = {
  readonly name: string;
  readonly part: string;
};

export type SheetInventory = ResolvedSheet & {
  readonly dimension: string;
  readonly formulaCells: number;
  readonly mergedRanges: number;
  readonly externalFormulaReferences: number;
};

export type FingerprintCount = {
  readonly count: number;
  readonly fingerprint: string;
};

export type BaselineInventory = {
  readonly externalLinks: FingerprintCount;
  readonly definedNames: {
    readonly count: number;
    readonly fingerprint: string;
    readonly problemCount: number;
    readonly problemFingerprint: string;
    readonly externalCount: number;
    readonly externalFingerprint: string;
  };
  readonly formulaErrors: {
    readonly formulaTextCount: number;
    readonly formulaTextFingerprint: string;
    readonly cachedErrorCount: number;
    readonly cachedErrorFingerprint: string;
  };
  readonly calcChain: {
    readonly present: boolean;
    readonly entryCount: number;
    readonly fingerprint: string;
  };
};
