import assert from "node:assert/strict";
import test from "node:test";
import { terminateOwnedProcessTree } from "../../scripts/process-tree.mjs";

// allow: SIZE_OK — one deterministic matrix for the process-tree safety contract.
test("Given 100ns-separated nested children with mixed offsets When cleanup runs Then only captured identities terminate deepest-first", async () => {
  const rows = [
    identity(901, 1, "2026-07-24T00:00:00.0000000Z"),
    identity(902, 901, "2026-07-24T09:00:00.0000001+09:00"),
    identity(903, 902, "2026-07-23T20:00:00.0000002-04:00"),
    identity(904, 1, "2026-07-24T00:00:00.0000003Z")
  ];
  const terminated = [];
  const provider = fakeProvider(rows, terminated);

  const result = await terminate(rows[0], provider);

  assert.deepEqual(
    terminated.map((item) => item.pid),
    [901, 903, 902]
  );
  assert.deepEqual(result.descendantPids, [902, 903]);
  assert.deepEqual(result.remainingPids, []);
  assert.equal(terminated.some((item) => item.pid === 904), false);
});

test("Given a reused PID before termination When cleanup validates identity Then unrelated kill count is zero", async () => {
  const rows = [
    identity(911, 1, "2026-07-24T00:00:00.0000000Z")
  ];
  const terminated = [];
  let snapshots = 0;
  const provider = {
    snapshot: async () => {
      snapshots += 1;
      return snapshots === 1
        ? [...rows]
        : [identity(911, 1, "2026-07-24T00:01:00.0000000Z")];
    },
    terminate: async (expected) => {
      terminated.push(expected);
      return "terminated";
    }
  };

  await assert.rejects(
    () => terminate(rows[0], provider),
    /PROCESS_TREE_ROOT_IDENTITY_REUSED/
  );
  assert.deepEqual(terminated, []);
});

test("Given a root PID was reused before cleanup When its spawn identity is supplied Then unrelated kill count is zero", async () => {
  const expected = identity(
    921,
    1,
    "2026-07-24T00:00:00.0000000Z"
  );
  const terminated = [];
  const provider = fakeProvider([
    identity(921, 1, "2026-07-24T00:01:00.0000000Z")
  ], terminated);

  await assert.rejects(
    () => terminate(expected, provider),
    /PROCESS_TREE_ROOT_IDENTITY_REUSED/
  );
  assert.deepEqual(terminated, []);
});

test("Given only a numeric Windows PID When cleanup starts Then it fails before any termination", async () => {
  const provider = fakeProvider([], []);
  await assert.rejects(
    () => terminateOwnedProcessTree(921, { provider }),
    /PROCESS_TREE_ROOT_IDENTITY_REQUIRED/
  );
});

test("Given a provider operation never settles When its nonzero timeout expires Then cleanup fails", async () => {
  const root = identity(925, 1, "2026-07-24T00:00:00.0000000Z");
  const provider = { snapshot: () => new Promise(() => {}) };
  await assert.rejects(
    () => terminateOwnedProcessTree(root, { provider, timeoutMs: 10 }),
    /PROCESS_TREE_SETTLE_TIMEOUT/
  );
});

test("Given a descendant has a noncanonical UTC offset When ownership parsing fails Then no process is terminated", async () => {
  const root = identity(926, 1, "2026-07-24T00:00:00.0000000Z");
  const invalid = identity(927, 926, "2026-07-24T14:00:00.0000001+14:01");
  const terminated = [];
  const provider = fakeProvider([root, invalid], terminated);
  await assert.rejects(
    () => terminate(root, provider),
    /PROCESS_TREE_CREATION_DATE_INVALID:927/
  );
  assert.deepEqual(terminated, []);
});

test("Given a stale child predates its reused parent PID When cleanup walks the tree Then the stale child survives", async () => {
  const rows = [
    identity(931, 1, "2026-07-24T00:01:00.0000000Z"),
    identity(932, 931, "2026-07-24T00:00:00.0000000Z"),
    identity(933, 931, "2026-07-24T00:02:00.0000000Z")
  ];
  const terminated = [];
  const provider = fakeProvider(rows, terminated);

  const result = await terminate(rows[0], provider);

  assert.deepEqual(
    terminated.map((item) => item.pid),
    [931, 933]
  );
  assert.equal(terminated.some((item) => item.pid === 932), false);
  assert.deepEqual(result.descendantPids, [933]);
});

test("Given children appear under a replacement root When cleanup rescans Then both survive with a nonzero receipt", async () => {
  const root = identity(
    941,
    1,
    "2026-07-24T00:00:00.0000000Z"
  );
  const lateChild = identity(
    942,
    941,
    "2026-07-24T00:00:01.0000000Z"
  );
  const replacement = identity(
    941,
    1,
    "2026-07-24T00:00:10.0000000Z"
  );
  const unrelated = identity(
    943,
    941,
    "2026-07-24T00:00:11.0000000Z"
  );
  const live = new Map([[root.pid, root]]);
  const terminated = [];
  const provider = {
    snapshot: async () => [...live.values()],
    terminate: async (expected) => {
      terminated.push(expected);
      live.delete(expected.pid);
      if (expected.pid === root.pid) {
        live.set(replacement.pid, replacement);
        live.set(lateChild.pid, lateChild);
        live.set(unrelated.pid, unrelated);
      }
      return "terminated";
    }
  };

  await assert.rejects(
    () => terminate(root, provider),
    /PROCESS_TREE_AMBIGUOUS_IDENTITIES:942,943/
  );
  assert.deepEqual(
    terminated.map((item) => item.pid),
    [941]
  );
  assert.equal(terminated.some((item) => item.pid === 942), false);
  assert.equal(terminated.some((item) => item.pid === 943), false);
});

test("Given a replacement root exits before its child is scanned When cleanup cannot prove the parent identity Then the orphan survives with a nonzero receipt", async () => {
  const root = identity(946, 1, "2026-07-24T00:00:00.0000000Z");
  const orphan = identity(947, 946, "2026-07-24T00:00:01.0000000Z");
  const live = new Map([[root.pid, root]]);
  const terminated = [];
  const provider = {
    snapshot: async () => [...live.values()],
    terminate: async (expected) => {
      terminated.push(expected);
      live.delete(expected.pid);
      live.set(orphan.pid, orphan);
      return "terminated";
    }
  };

  await assert.rejects(
    () => terminate(root, provider),
    /PROCESS_TREE_AMBIGUOUS_IDENTITIES:947/
  );
  assert.deepEqual(
    terminated.map((item) => item.pid),
    [946]
  );
});

test("Given an orphan appears after an empty rescan When cleanup reaches a fixed point Then it survives with a nonzero receipt", async () => {
  const root = identity(
    951,
    1,
    "2026-07-24T00:00:00.0000000Z"
  );
  const lateChild = identity(
    952,
    951,
    "2026-07-24T00:00:01.0000000Z"
  );
  const snapshots = [[root], [root], [], [lateChild], [lateChild], [], []];
  const terminated = [];
  const provider = {
    snapshot: async () => snapshots.shift() ?? [],
    terminate: async (expected) => {
      terminated.push(expected);
      return "terminated";
    }
  };

  await assert.rejects(
    () => terminate(root, provider),
    /PROCESS_TREE_AMBIGUOUS_IDENTITIES:952/
  );
  assert.deepEqual(
    terminated.map((item) => item.pid),
    [951]
  );
});

test("Given a grandchild appears while its root terminates When cleanup rescans all owned parents Then deepest exact identities terminate", async () => {
  const root = identity(
    961,
    1,
    "2026-07-24T00:00:00.0000000Z"
  );
  const child = identity(
    962,
    961,
    "2026-07-24T00:00:01.0000000Z"
  );
  const lateGrandchild = identity(
    963,
    962,
    "2026-07-24T00:00:02.0000000Z"
  );
  const live = new Map([
    [root.pid, root],
    [child.pid, child]
  ]);
  const terminated = [];
  const provider = {
    snapshot: async () => [...live.values()],
    terminate: async (expected) => {
      terminated.push(expected);
      live.delete(expected.pid);
      if (expected.pid === root.pid) {
        live.set(lateGrandchild.pid, lateGrandchild);
      }
      return "terminated";
    }
  };

  const result = await terminate(root, provider);

  assert.deepEqual(
    terminated.map((item) => item.pid),
    [961, 963, 962]
  );
  assert.deepEqual(result.descendantPids, [962, 963]);
  assert.deepEqual(result.remainingPids, []);
});

test("Given a child PID is reused inside its terminate call When cleanup rescans Then the replacement subtree survives", async () => {
  const root = identity(
    971,
    1,
    "2026-07-24T00:00:00.0000000Z"
  );
  const child = identity(
    972,
    971,
    "2026-07-24T00:00:01.0000000Z"
  );
  const replacement = identity(
    972,
    1,
    "2026-07-24T00:00:10.0000000Z"
  );
  const unrelated = identity(
    973,
    972,
    "2026-07-24T00:00:11.0000000Z"
  );
  const live = new Map([
    [root.pid, root],
    [child.pid, child]
  ]);
  const terminated = [];
  const provider = {
    snapshot: async () => [...live.values()],
    terminate: async (expected) => {
      if (expected.pid === child.pid) {
        live.set(replacement.pid, replacement);
        live.set(unrelated.pid, unrelated);
        return "reused";
      }
      terminated.push(expected);
      live.delete(expected.pid);
      return "terminated";
    }
  };

  await assert.rejects(
    () => terminate(root, provider),
    /PROCESS_TREE_AMBIGUOUS_IDENTITIES:972,973/
  );
  assert.deepEqual(
    terminated.map((item) => item.pid),
    [971]
  );
});

function identity(pid, parentPid, creationDate) {
  return { pid, parentPid, creationDate };
}

function terminate(root, provider) {
  return terminateOwnedProcessTree(root, {
    clock: () => Date.parse("2026-07-24T01:00:00.000Z"),
    provider,
    settle: async () => {}
  });
}

function fakeProvider(initialRows, terminated) {
  const live = new Map(initialRows.map((row) => [row.pid, row]));
  return {
    snapshot: async () => [...live.values()],
    terminate: async (expected) => {
      const current = live.get(expected.pid);
      if (
        current === undefined ||
        current.creationDate !== expected.creationDate
      ) {
        return current === undefined ? "absent" : "reused";
      }
      terminated.push(expected);
      live.delete(expected.pid);
      return "terminated";
    }
  };
}
