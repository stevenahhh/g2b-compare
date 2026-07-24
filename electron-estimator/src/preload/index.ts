import type { z } from "zod";
import {
  BuildInfoRequestSchema,
  DialogRequestSchema,
  DialogResponseSchema,
  ExportRequestSchema,
  ExportResponseSchema,
  IPC_CHANNELS,
  ImportRequestSchema,
  ImportResponseSchema,
  MainBuildInfoResponseSchema,
  ReadSeedRequestSchema,
  ReadSeedResponseSchema,
  RuntimeBuildInfoResponseSchema,
  bridgeError,
  type DialogRequest,
  type ExportRequest,
  type ImportRequest,
  type ReadSeedRequest
} from "../main/ipc-contracts.js";

declare const require: (id: "electron") => typeof import("electron");

const { contextBridge, ipcRenderer } = require("electron");

type InvokeRequest<Input, ResponseSchema extends z.ZodType> = {
  readonly channel: (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];
  readonly request: unknown;
  readonly requestSchema: z.ZodType<Input>;
  readonly responseSchema: ResponseSchema;
};

async function invoke<Input, ResponseSchema extends z.ZodType>(
  invocation: InvokeRequest<Input, ResponseSchema>
): Promise<z.output<ResponseSchema>> {
  const request = invocation.requestSchema.safeParse(invocation.request);
  if (!request.success) {
    return invocation.responseSchema.parse(
      bridgeError("IPC_PAYLOAD_REJECTED")
    );
  }
  try {
    const rawResponse: unknown = await ipcRenderer.invoke(
      invocation.channel,
      request.data
    );
    const response = invocation.responseSchema.safeParse(rawResponse);
    return response.success
      ? response.data
      : invocation.responseSchema.parse(
          bridgeError("IPC_RESPONSE_REJECTED")
        );
  } catch (error) {
    if (error instanceof Error) {
      return invocation.responseSchema.parse(
        bridgeError("IPC_INTERNAL_ERROR")
      );
    }
    throw error;
  }
}

const estimator = Object.freeze({
  dialog: (request: DialogRequest) =>
    invoke({
      channel: IPC_CHANNELS.dialog,
      request,
      requestSchema: DialogRequestSchema,
      responseSchema: DialogResponseSchema
    }),
  import: (request: ImportRequest) =>
    invoke({
      channel: IPC_CHANNELS.import,
      request,
      requestSchema: ImportRequestSchema,
      responseSchema: ImportResponseSchema
    }),
  export: (request: ExportRequest) =>
    invoke({
      channel: IPC_CHANNELS.export,
      request,
      requestSchema: ExportRequestSchema,
      responseSchema: ExportResponseSchema
    }),
  readSeed: (request: ReadSeedRequest = {}) =>
    invoke({
      channel: IPC_CHANNELS.readSeed,
      request,
      requestSchema: ReadSeedRequestSchema,
      responseSchema: ReadSeedResponseSchema
    }),
  getBuildInfo: async () => {
    const response = await invoke({
      channel: IPC_CHANNELS.getBuildInfo,
      request: {},
      requestSchema: BuildInfoRequestSchema,
      responseSchema: MainBuildInfoResponseSchema
    });
    if (!response.ok) {
      return RuntimeBuildInfoResponseSchema.parse(response);
    }
    return RuntimeBuildInfoResponseSchema.parse({
      ok: true,
      value: {
        ...response.value,
        sandboxed: process.sandboxed,
        contextIsolated: process.contextIsolated
      }
    });
  }
});

contextBridge.exposeInMainWorld("estimator", estimator);
