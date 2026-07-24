import { LegacyImportError } from "./errors.js";

export const ZIP_LIMITS = {
  maxSourceBytes: 32 * 1024 * 1024,
  maxMembers: 2_048,
  maxMemberUncompressedBytes: 64 * 1024 * 1024,
  maxTotalUncompressedBytes: 256 * 1024 * 1024,
  maxCompressionRatio: 1_000,
  maxMemberNameBytes: 1_024
} as const;

export type ZipMember = {
  readonly name: string;
  readonly compressedBytes: number;
  readonly uncompressedBytes: number;
  readonly localHeaderOffset: number;
  readonly flags: number;
  readonly compressionMethod: number;
  readonly rawName: Uint8Array;
};

const SIGNATURE = {
  local: 0x04034b50,
  central: 0x02014b50,
  eocd: 0x06054b50
} as const;

export function scanCentralDirectory(bytes: Uint8Array): readonly ZipMember[] {
  if (bytes.byteLength > ZIP_LIMITS.maxSourceBytes) {
    throw new LegacyImportError("ZIP_LIMIT_EXCEEDED");
  }
  const buffer = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const eocd = findEocd(buffer);
  if (eocd < 0) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  const disk = buffer.readUInt16LE(eocd + 4);
  const centralDisk = buffer.readUInt16LE(eocd + 6);
  const diskMembers = buffer.readUInt16LE(eocd + 8);
  const memberCount = buffer.readUInt16LE(eocd + 10);
  const centralBytes = buffer.readUInt32LE(eocd + 12);
  const centralOffset = buffer.readUInt32LE(eocd + 16);
  if (
    disk !== 0 ||
    centralDisk !== 0 ||
    diskMembers !== memberCount ||
    memberCount === 0xffff ||
    centralBytes === 0xffffffff ||
    centralOffset === 0xffffffff
  ) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  if (memberCount > ZIP_LIMITS.maxMembers) {
    throw new LegacyImportError("ZIP_LIMIT_EXCEEDED");
  }
  const centralEnd = centralOffset + centralBytes;
  if (centralEnd !== eocd || centralEnd > buffer.length) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }

  const members: ZipMember[] = [];
  const names = new Set<string>();
  const localOffsets = new Set<number>();
  let cursor = centralOffset;
  let totalUncompressed = 0;
  for (let index = 0; index < memberCount; index += 1) {
    if (
      cursor + 46 > centralEnd ||
      buffer.readUInt32LE(cursor) !== SIGNATURE.central
    ) {
      throw new LegacyImportError("CORRUPT_OOXML");
    }
    const flags = buffer.readUInt16LE(cursor + 8);
    const compressionMethod = buffer.readUInt16LE(cursor + 10);
    const compressedBytes = buffer.readUInt32LE(cursor + 20);
    const uncompressedBytes = buffer.readUInt32LE(cursor + 24);
    const nameBytes = buffer.readUInt16LE(cursor + 28);
    const extraBytes = buffer.readUInt16LE(cursor + 30);
    const commentBytes = buffer.readUInt16LE(cursor + 32);
    const startDisk = buffer.readUInt16LE(cursor + 34);
    const localHeaderOffset = buffer.readUInt32LE(cursor + 42);
    const recordEnd = cursor + 46 + nameBytes + extraBytes + commentBytes;
    if (
      recordEnd > centralEnd ||
      startDisk !== 0 ||
      compressedBytes === 0xffffffff ||
      uncompressedBytes === 0xffffffff ||
      localHeaderOffset === 0xffffffff
    ) {
      throw new LegacyImportError("CORRUPT_OOXML");
    }
    const rawName = buffer.subarray(cursor + 46, cursor + 46 + nameBytes);
    const name = decodeMemberName(rawName, flags);
    assertSafeMember(name, rawName.byteLength, names);
    assertMemberLimits(compressedBytes, uncompressedBytes);
    if (
      (flags & 1) !== 0 ||
      (compressionMethod !== 0 && compressionMethod !== 8)
    ) {
      throw new LegacyImportError("UNSAFE_ZIP_ENTRY");
    }
    if (localOffsets.has(localHeaderOffset)) {
      throw new LegacyImportError("CORRUPT_OOXML");
    }
    localOffsets.add(localHeaderOffset);
    const member = {
      name,
      compressedBytes,
      uncompressedBytes,
      localHeaderOffset,
      flags,
      compressionMethod,
      rawName
    };
    verifyLocalHeader(buffer, member, centralOffset);
    totalUncompressed += uncompressedBytes;
    if (totalUncompressed > ZIP_LIMITS.maxTotalUncompressedBytes) {
      throw new LegacyImportError("ZIP_LIMIT_EXCEEDED");
    }
    members.push(member);
    cursor = recordEnd;
  }
  if (cursor !== centralEnd) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  return members;
}

function findEocd(buffer: Buffer): number {
  const minimum = Math.max(0, buffer.length - 65_557);
  for (let offset = buffer.length - 22; offset >= minimum; offset -= 1) {
    if (
      buffer.readUInt32LE(offset) === SIGNATURE.eocd &&
      offset + 22 + buffer.readUInt16LE(offset + 20) === buffer.length
    ) {
      return offset;
    }
  }
  return -1;
}

function decodeMemberName(rawName: Uint8Array, flags: number): string {
  if ((flags & 0x800) === 0 && rawName.some((byte) => byte > 0x7f)) {
    throw new LegacyImportError("UNSAFE_ZIP_ENTRY");
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(rawName);
  } catch {
    throw new LegacyImportError("UNSAFE_ZIP_ENTRY");
  }
}

function assertSafeMember(
  name: string,
  nameBytes: number,
  names: Set<string>
): void {
  const segments = name.endsWith("/")
    ? name.slice(0, -1).split("/")
    : name.split("/");
  if (
    name.length === 0 ||
    nameBytes > ZIP_LIMITS.maxMemberNameBytes ||
    name.startsWith("/") ||
    name.includes("\\") ||
    name.includes("\0") ||
    segments.some(
      (segment) => segment === "" || segment === "." || segment === ".."
    ) ||
    segments[0]?.includes(":") === true ||
    names.has(name)
  ) {
    throw new LegacyImportError("UNSAFE_ZIP_ENTRY");
  }
  names.add(name);
}

function assertMemberLimits(compressed: number, uncompressed: number): void {
  const ratio = compressed === 0 ? uncompressed : uncompressed / compressed;
  if (
    uncompressed > ZIP_LIMITS.maxMemberUncompressedBytes ||
    (uncompressed > 1024 * 1024 && ratio > ZIP_LIMITS.maxCompressionRatio)
  ) {
    throw new LegacyImportError("ZIP_LIMIT_EXCEEDED");
  }
}

function verifyLocalHeader(
  buffer: Buffer,
  member: ZipMember,
  centralOffset: number
): void {
  const offset = member.localHeaderOffset;
  if (
    offset + 30 > centralOffset ||
    buffer.readUInt32LE(offset) !== SIGNATURE.local
  ) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  const flags = buffer.readUInt16LE(offset + 6);
  const method = buffer.readUInt16LE(offset + 8);
  const nameBytes = buffer.readUInt16LE(offset + 26);
  const extraBytes = buffer.readUInt16LE(offset + 28);
  const dataStart = offset + 30 + nameBytes + extraBytes;
  const localName = buffer.subarray(offset + 30, offset + 30 + nameBytes);
  if (
    flags !== member.flags ||
    method !== member.compressionMethod ||
    !localName.equals(Buffer.from(member.rawName)) ||
    dataStart + member.compressedBytes > centralOffset
  ) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  if (
    (flags & 8) === 0 &&
    (
      buffer.readUInt32LE(offset + 18) !== member.compressedBytes ||
      buffer.readUInt32LE(offset + 22) !== member.uncompressedBytes
    )
  ) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
}
