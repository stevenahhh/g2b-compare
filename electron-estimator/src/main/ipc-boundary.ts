import type {
  BrowserWindow,
  IpcMainInvokeEvent
} from "electron";
import type { z } from "zod";
import {
  CapabilityRejectedError,
  type FrameIdentity
} from "./capabilities.js";
import {
  BRIDGE_ERROR_MESSAGES,
  bridgeError,
  type BridgeErrorCode
} from "./ipc-contracts.js";
import { APP_ORIGIN } from "./protocol.js";

export type SenderSnapshot = {
  readonly windowAlive: boolean;
  readonly senderWebContentsId: number;
  readonly windowWebContentsId: number;
  readonly senderFrame: {
    readonly url: string;
    readonly origin: string;
    readonly processId: number;
    readonly routingId: number;
  } | null;
  readonly mainFrame: FrameIdentity;
};

type BoundaryOperation<Input> = (
  request: Input,
  frame: FrameIdentity
) => Promise<unknown>;

type BoundaryRequest<Input, ResponseSchema extends z.ZodType> = {
  readonly sender: SenderSnapshot;
  readonly request: unknown;
  readonly requestSchema: z.ZodType<Input>;
  readonly responseSchema: ResponseSchema;
  readonly operation: BoundaryOperation<Input>;
};

class IpcBoundaryError extends Error {
  readonly name = "IpcBoundaryError";

  constructor(readonly code: BridgeErrorCode) {
    super(BRIDGE_ERROR_MESSAGES[code]);
  }
}

export class OperationUnavailableError extends Error {
  readonly name = "OperationUnavailableError";
}

export async function executeIpcBoundary<
  Input,
  ResponseSchema extends z.ZodType
>(
  boundary: BoundaryRequest<Input, ResponseSchema>
): Promise<z.output<ResponseSchema>> {
  try {
    const frame = validateSender(boundary.sender);
    const request = boundary.requestSchema.safeParse(boundary.request);
    if (!request.success) {
      return boundary.responseSchema.parse(
        bridgeError("IPC_PAYLOAD_REJECTED")
      );
    }
    const value = await boundary.operation(request.data, frame);
    const response = boundary.responseSchema.safeParse({
      ok: true,
      value
    });
    if (!response.success) {
      return boundary.responseSchema.parse(
        bridgeError("IPC_RESPONSE_REJECTED")
      );
    }
    return response.data;
  } catch (error) {
    if (error instanceof IpcBoundaryError) {
      return boundary.responseSchema.parse(bridgeError(error.code));
    }
    if (error instanceof CapabilityRejectedError) {
      return boundary.responseSchema.parse(
        bridgeError("IPC_CAPABILITY_REJECTED")
      );
    }
    if (error instanceof OperationUnavailableError) {
      return boundary.responseSchema.parse(
        bridgeError("IPC_OPERATION_UNAVAILABLE")
      );
    }
    if (error instanceof Error) {
      return boundary.responseSchema.parse(bridgeError("IPC_INTERNAL_ERROR"));
    }
    throw error;
  }
}

export function senderSnapshot(
  event: IpcMainInvokeEvent,
  mainWindow: BrowserWindow
): SenderSnapshot {
  const senderFrame = event.senderFrame;
  const mainFrame = mainWindow.webContents.mainFrame;
  return {
    windowAlive:
      !mainWindow.isDestroyed() && !mainWindow.webContents.isDestroyed(),
    senderWebContentsId: event.sender.id,
    windowWebContentsId: mainWindow.webContents.id,
    senderFrame:
      senderFrame === null
        ? null
        : {
            url: senderFrame.url,
            origin: senderFrame.origin,
            processId: senderFrame.processId,
            routingId: senderFrame.routingId
          },
    mainFrame: {
      processId: mainFrame.processId,
      routingId: mainFrame.routingId
    }
  };
}

function validateSender(sender: SenderSnapshot): FrameIdentity {
  const frame = sender.senderFrame;
  const parsedUrl =
    frame !== null && URL.canParse(frame.url) ? new URL(frame.url) : null;
  if (
    !sender.windowAlive ||
    sender.senderWebContentsId !== sender.windowWebContentsId ||
    frame === null ||
    frame.origin !== APP_ORIGIN ||
    parsedUrl === null ||
    parsedUrl.protocol !== "app:" ||
    parsedUrl.hostname !== "app" ||
    frame.processId !== sender.mainFrame.processId ||
    frame.routingId !== sender.mainFrame.routingId
  ) {
    throw new IpcBoundaryError("IPC_SENDER_REJECTED");
  }
  return {
    processId: frame.processId,
    routingId: frame.routingId
  };
}
