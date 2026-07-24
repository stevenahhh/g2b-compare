import { spawn } from "node:child_process";

// allow: SIZE_OK — one auditable Windows exact-identity termination state machine.
export async function terminateOwnedProcessTree(root, options = {}) {
  const rootPid = typeof root === "number" ? root : root.pid;
  if (!Number.isSafeInteger(rootPid) || rootPid <= 0) {
    throw new TypeError("PROCESS_TREE_ROOT_PID_INVALID");
  }
  if (process.platform !== "win32" && options.provider === undefined) {
    process.kill(rootPid, "SIGTERM");
    return emptyResult(rootPid, []);
  }
  if (typeof root === "number") {
    throw new TypeError("PROCESS_TREE_ROOT_IDENTITY_REQUIRED");
  }
  const provider = options.provider ?? windowsProcessProvider;
  const timeoutMs = options.timeoutMs ?? 10_000;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    throw new TypeError("PROCESS_TREE_TIMEOUT_INVALID");
  }
  const signal = AbortSignal.timeout(timeoutMs);
  const timeout = new Promise((resolvePromise, rejectPromise) => {
    signal.addEventListener(
      "abort",
      () => rejectPromise(new TypeError("PROCESS_TREE_SETTLE_TIMEOUT")),
      { once: true }
    );
  });
  const bounded = (operation) => Promise.race([operation, timeout]);
  const clock = options.clock ?? Date.now;
  const settle =
    options.settle ??
    (provider === windowsProcessProvider
      ? () => new Promise((resolvePromise) => setTimeout(resolvePromise, 100))
      : async () => {});
  const initial = await bounded(provider.snapshot(signal));
  const currentRoot = initial.find((item) => item.pid === rootPid);
  if (currentRoot === undefined) {
    throw new TypeError(`PROCESS_TREE_ROOT_IDENTITY_NOT_FOUND:${rootPid}`);
  }
  if (currentRoot.creationDate !== root.creationDate) {
    throw new TypeError(`PROCESS_TREE_ROOT_IDENTITY_REUSED:${rootPid}`);
  }
  const ambiguousPids = [];
  const records = collectDescendants(currentRoot, initial, ambiguousPids);
  const skippedReusedPids = [];
  const context = {
    ambiguousPids,
    bounded,
    clock,
    provider,
    signal,
    skippedReusedPids
  };
  const rootOutcome = await terminateRecord(records[0], context);
  if (rootOutcome === "reused") {
    throw new TypeError(`PROCESS_TREE_ROOT_IDENTITY_REUSED:${rootPid}`);
  }

  let stableSnapshots = 0;
  let final = initial;
  for (let pass = 0; pass < 64 && !signal.aborted; pass += 1) {
    await bounded(settle(signal));
    final = await bounded(provider.snapshot(signal));
    const added = discoverDescendants(records, final, ambiguousPids);
    const pending = records
      .filter(
        (record) =>
          record.depth !== 0 &&
          record.terminatedAt === undefined &&
          final.some(
            (item) =>
              item.pid === record.identity.pid &&
              item.creationDate === record.identity.creationDate
          )
      )
      .sort(
        (left, right) =>
          right.depth - left.depth ||
          compareCreationNewestFirst(left.identity, right.identity)
      );
    for (const record of pending) {
      await terminateRecord(record, context);
    }
    if (added === 0 && pending.length === 0) {
      stableSnapshots += 1;
      if (stableSnapshots === 2) {
        break;
      }
    } else {
      stableSnapshots = 0;
    }
  }
  if (stableSnapshots !== 2) {
    throw new TypeError("PROCESS_TREE_SETTLE_TIMEOUT");
  }

  const remainingPids = records
    .filter((record) =>
      final.some(
        (item) =>
          item.pid === record.identity.pid &&
          item.creationDate === record.identity.creationDate
      )
    )
    .map((record) => record.identity.pid);
  if (remainingPids.length !== 0) {
    throw new TypeError(
      `PROCESS_TREE_TERMINATION_FAILED:${remainingPids.join(",")}`
    );
  }
  const ambiguous = [...new Set([...skippedReusedPids, ...ambiguousPids])];
  if (ambiguous.length !== 0) {
    throw new TypeError(
      `PROCESS_TREE_AMBIGUOUS_IDENTITIES:${ambiguous.join(",")}`
    );
  }
  return {
    rootPid,
    descendantPids: records.slice(1).map((record) => record.identity.pid),
    remainingPids,
    skippedReusedPids: [...new Set(skippedReusedPids)]
  };
}

function emptyResult(rootPid, skippedReusedPids) {
  return { rootPid, descendantPids: [], remainingPids: [], skippedReusedPids };
}

function collectDescendants(root, snapshot, ambiguousPids) {
  const records = [{ identity: root, depth: 0, terminatedAt: undefined }];
  discoverDescendants(records, snapshot, ambiguousPids);
  return records;
}

function discoverDescendants(records, snapshot, ambiguousPids) {
  let added = 0;
  for (let index = 0; index < records.length; index += 1) {
    const parent = records[index];
    const parentIsExactLive = snapshot.some(
      (item) =>
        item.pid === parent.identity.pid &&
        item.creationDate === parent.identity.creationDate
    );
    for (const candidate of snapshot) {
      const candidateAt = creationTicks(candidate);
      if (
        candidate.parentPid !== parent.identity.pid ||
        candidateAt <= creationTicks(parent.identity) ||
        records.some(
          (record) =>
            record.identity.pid === candidate.pid &&
            record.identity.creationDate === candidate.creationDate
        )
      ) {
        continue;
      }
      if (!parentIsExactLive) {
        ambiguousPids.push(candidate.pid);
        continue;
      }
      records.push({
        identity: candidate,
        depth: parent.depth + 1,
        terminatedAt: undefined
      });
      added += 1;
    }
  }
  return added;
}

async function terminateRecord(record, context) {
  const current = (
    await context.bounded(context.provider.snapshot(context.signal))
  ).find((item) => item.pid === record.identity.pid);
  if (
    current !== undefined &&
    current.creationDate !== record.identity.creationDate
  ) {
    record.terminatedAt = creationTicks(current);
    context.skippedReusedPids.push(record.identity.pid);
    return "reused";
  }
  if (current === undefined) {
    record.terminatedAt = context.clock();
    return "absent";
  }
  const outcome = await context.bounded(
    context.provider.terminate(record.identity, context.signal)
  );
  if (outcome === "reused") {
    const replacement = (
      await context.bounded(context.provider.snapshot(context.signal))
    ).find((item) => item.pid === record.identity.pid);
    record.terminatedAt =
      replacement === undefined ? context.clock() : creationTicks(replacement);
    context.skippedReusedPids.push(record.identity.pid);
    return outcome;
  }
  record.terminatedAt = context.clock();
  return outcome;
}

function compareCreationNewestFirst(left, right) {
  const leftTicks = creationTicks(left);
  const rightTicks = creationTicks(right);
  return rightTicks > leftTicks ? 1 : rightTicks < leftTicks ? -1 : 0;
}

function creationTicks(identity) {
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{1,7})(Z|([+-])(\d{2}):(\d{2}))$/u.exec(
      identity.creationDate
    );
  const values = match?.slice(1, 7).map(Number);
  const fraction = match?.[7];
  const zone = match?.[8];
  if (
    match === null ||
    values === undefined ||
    fraction === undefined ||
    zone === undefined
  ) {
    throw new TypeError(
      `PROCESS_TREE_CREATION_DATE_INVALID:${String(identity.pid)}`
    );
  }
  const [year, month, day, hour, minute, second] = values;
  const localMilliseconds = Date.UTC(
    year,
    month - 1,
    day,
    hour,
    minute,
    second
  );
  const roundTrip = new Date(localMilliseconds);
  if (
    roundTrip.getUTCFullYear() !== year ||
    roundTrip.getUTCMonth() !== month - 1 ||
    roundTrip.getUTCDate() !== day ||
    roundTrip.getUTCHours() !== hour ||
    roundTrip.getUTCMinutes() !== minute ||
    roundTrip.getUTCSeconds() !== second
  ) {
    throw new TypeError(
      `PROCESS_TREE_CREATION_DATE_INVALID:${String(identity.pid)}`
    );
  }
  const offsetMinutes =
    zone === "Z"
      ? 0
      : (match[9] === "+" ? 1 : -1) *
        (Number(match[10]) * 60 + Number(match[11]));
  if (Math.abs(offsetMinutes) > 14 * 60 || Number(match[11]) > 59) {
    throw new TypeError(
      `PROCESS_TREE_CREATION_DATE_INVALID:${String(identity.pid)}`
    );
  }
  return (
    BigInt(localMilliseconds - offsetMinutes * 60_000) * 10_000n +
    BigInt(fraction.padEnd(7, "0"))
  );
}

export async function captureProcessIdentity(pid, provider = windowsProcessProvider) {
  const identity = (await provider.snapshot()).find((item) => item.pid === pid);
  if (identity === undefined) {
    throw new TypeError(`PROCESS_IDENTITY_NOT_FOUND:${String(pid)}`);
  }
  return { pid: identity.pid, creationDate: identity.creationDate };
}

export async function isProcessIdentityAlive(
  identity,
  provider = windowsProcessProvider
) {
  return (await provider.snapshot()).some(
    (item) =>
      item.pid === identity.pid &&
      item.creationDate === identity.creationDate
  );
}

const windowsProcessProvider = {
  snapshot: async (signal) => {
    const script = [
      "$items=@(Get-CimInstance Win32_Process | ForEach-Object {",
      "[pscustomobject]@{",
      "pid=[int]$_.ProcessId;",
      "parentPid=[int]$_.ParentProcessId;",
      "creationDate=$_.CreationDate.ToUniversalTime().ToString('o')",
      "}})",
      "ConvertTo-Json -InputObject $items -Compress"
    ].join("\n");
    return JSON.parse((await powershell(script, signal)) || "[]");
  },
  terminate: async (identity, signal) => {
    const expected = psLiteral(identity.creationDate);
    const script = [
      `$item=Get-CimInstance Win32_Process -Filter "ProcessId=${String(identity.pid)}"`,
      "if($null -eq $item){'absent';exit 0}",
      `$actual=$item.CreationDate.ToUniversalTime().ToString('o');if($actual -ne '${expected}'){'reused';exit 0}`,
      "$result=Invoke-CimMethod -InputObject $item -MethodName Terminate",
      "if([int]$result.ReturnValue -ne 0){Write-Error ('terminate:'+ $result.ReturnValue);exit 1}",
      "'terminated'"
    ].join("\n");
    return powershell(script, signal);
  }
};

function psLiteral(value) {
  return value.replaceAll("'", "''");
}

function powershell(script, signal) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      { shell: false, signal, windowsHide: true }
    );
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.once("error", rejectPromise);
    child.once("close", (code) => {
      if (code === 0) {
        resolvePromise(stdout.trim());
      } else {
        rejectPromise(
          new TypeError(
            `PROCESS_TREE_COMMAND_FAILED:${String(code)}:${stderr.trim()}`
          )
        );
      }
    });
  });
}
