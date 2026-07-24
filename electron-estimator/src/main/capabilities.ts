import { randomUUID } from "node:crypto";

export type CapabilityKind = "import" | "export";

export type FrameIdentity = {
  readonly processId: number;
  readonly routingId: number;
};

type Capability = {
  readonly kind: CapabilityKind;
  readonly selectedPath: string;
  readonly frame: FrameIdentity;
  readonly expiresAt: number;
};

type CapabilityStoreOptions = {
  readonly ttlMs?: number;
  readonly now?: () => number;
  readonly createId?: () => string;
};

type ConsumeCapability = {
  readonly capabilityId: string;
  readonly kind: CapabilityKind;
  readonly frame: FrameIdentity;
};

export class CapabilityRejectedError extends Error {
  readonly name = "CapabilityRejectedError";
}

export class CapabilityStore {
  readonly #capabilities = new Map<string, Capability>();
  readonly #ttlMs: number;
  readonly #now: () => number;
  readonly #createId: () => string;

  constructor(options: CapabilityStoreOptions = {}) {
    this.#ttlMs = options.ttlMs ?? 120_000;
    this.#now = options.now ?? Date.now;
    this.#createId = options.createId ?? randomUUID;
  }

  issue(
    kind: CapabilityKind,
    selectedPath: string,
    frame: FrameIdentity
  ): string {
    const capabilityId = this.#createId();
    this.#capabilities.set(capabilityId, {
      kind,
      selectedPath,
      frame,
      expiresAt: this.#now() + this.#ttlMs
    });
    return capabilityId;
  }

  consume(request: ConsumeCapability): string {
    const capability = this.#capabilities.get(request.capabilityId);
    if (capability === undefined) {
      throw new CapabilityRejectedError();
    }
    if (capability.expiresAt < this.#now()) {
      this.#capabilities.delete(request.capabilityId);
      throw new CapabilityRejectedError();
    }
    if (
      capability.kind !== request.kind ||
      capability.frame.processId !== request.frame.processId ||
      capability.frame.routingId !== request.frame.routingId
    ) {
      throw new CapabilityRejectedError();
    }
    this.#capabilities.delete(request.capabilityId);
    return capability.selectedPath;
  }
}
