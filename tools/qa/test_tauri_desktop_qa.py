"""Unit tests for the packaged desktop QA parser and receipt boundary."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest

from tools.qa import tauri_desktop_qa
from tools.qa.tauri_desktop_qa import (
    HARNESS_SOURCE,
    INSTALLED_EXECUTABLE_NAME,
    QA_REPLAY_ESTIMATE_ID,
    QA_REPLAY_LINE_ID,
    InstalledApplication,
    InstalledChildProvenance,
    InstalledParityReceiptState,
    InstallerChain,
    ReceiptContext,
    ReceiptStatus,
    ReceiptStore,
    inject_qa_replay_mutation,
    installed_application_from_registry_values,
    installed_child_command,
    parse_args,
    record_post_chain_integrity,
    require_mapping,
    require_mapping_list,
    run_installed_parity,
    sha256_file,
    wait_for_devtools_active_port,
    wait_for_install_completion,
    wait_for_uninstall_completion,
)

# These tests live under tools/qa, so mirror the repository's normal test-file
# Ruff exceptions without changing shared configuration.
# ruff: noqa: D103, PLR2004, S101, S105, TC003


def _post_chain_receipt_state(
    tmp_path: Path,
) -> tuple[InstalledParityReceiptState, Path, dict[str, Path]]:
    run_dir = tmp_path / "install-chain"
    run_dir.mkdir()
    installer = tmp_path / "setup.exe"
    _ = installer.write_bytes(b"installer-artifact")
    installer_sha256 = sha256_file(installer)
    qa_harness_sha256 = sha256_file(HARNESS_SOURCE)
    installer_bytes = installer.stat().st_size
    executable_bytes = 8192
    executable_sha256 = "e" * 64
    child_receipts: dict[str, Path] = {}
    children: list[dict[str, object]] = []
    for scenario in ("full-parity", "adversarial"):
        child_receipt = run_dir / "children" / scenario / "child" / "receipt.json"
        child_receipt.parent.mkdir(parents=True)
        counts: dict[str, object] = {"failed": 0, "passed": 2, "unavailable": 0}
        receipt: dict[str, object] = {
            "schema_version": 1,
            "scenario": scenario,
            "outcome": ReceiptStatus.PASSED.value,
            "counts": counts,
            "qa_harness_sha256": qa_harness_sha256,
            "events": [
                {
                    "check": "launch-packaged-executable",
                    "status": ReceiptStatus.PASSED.value,
                    "details": {
                        "qa_harness_sha256": qa_harness_sha256,
                        "installer_bytes": installer_bytes,
                        "installer_sha256": installer_sha256,
                        "executable_bytes": executable_bytes,
                        "executable_sha256": executable_sha256,
                    },
                },
                {
                    "check": "cleanup",
                    "status": ReceiptStatus.PASSED.value,
                    "details": {},
                },
            ],
        }
        _ = child_receipt.write_text(
            json.dumps(receipt, sort_keys=True), encoding="utf-8"
        )
        child_receipts[scenario] = child_receipt
        children.append(
            {
                "scenario": scenario,
                "outcome": ReceiptStatus.PASSED.value,
                "counts": counts,
                "qa_harness_sha256": qa_harness_sha256,
                "receipt_path": child_receipt.relative_to(run_dir).as_posix(),
                "receipt_sha256": sha256_file(child_receipt),
            }
        )
    checks = (
        "preflight-clean-installed-state",
        "install-exact-nsis-silent",
        "child-full-parity",
        "child-adversarial",
        "silent-uninstall-evented-cleanup",
    )
    events: list[dict[str, object]] = [
        {
            "sequence": index,
            "timestamp": "2026-08-04T12:00:00Z",
            "check": check,
            "status": ReceiptStatus.PASSED.value,
            "details": {},
        }
        for index, check in enumerate(checks, start=1)
    ]
    return (
        InstalledParityReceiptState(
            run_id="install-chain",
            run_dir=run_dir,
            qa_harness_sha256=qa_harness_sha256,
            installer={
                "path": str(installer),
                "bytes": installer_bytes,
                "sha256": installer_sha256,
            },
            cleanup={
                "uninstaller_exit_code": 0,
                "directory_removed": True,
                "registry_removed": True,
                "process_cleanup": True,
                "ports_closed": True,
            },
            events=events,
            children=children,
            installed_executable={
                "path": str(tmp_path / "removed-g2b-compare-desktop.exe"),
                "bytes": executable_bytes,
                "sha256": executable_sha256,
            },
        ),
        installer,
        child_receipts,
    )


class _FakeDirectoryChanges:
    def __init__(self, marker: Path, events: list[str | None]) -> None:
        self.marker: Path = marker
        self.events: list[str | None] = events
        self.timeouts: list[int] = []
        self.closed: bool = False

    def wait_for_change(self, timeout_ms: int) -> bool:
        self.timeouts.append(timeout_ms)
        if not self.events:
            return False
        contents = self.events.pop(0)
        if contents is not None:
            self.marker.parent.mkdir(parents=True, exist_ok=True)
            _ = self.marker.write_text(contents, encoding="ascii")
        return True

    def close(self) -> None:
        self.closed = True


class _FakeRegistry:
    def __init__(self, installed: InstalledApplication | None = None) -> None:
        self.installed: InstalledApplication | None = installed

    def installed_application(self) -> InstalledApplication | None:
        return self.installed


class _FakePayloadDisappearingRegistry:
    def __init__(self, installed: InstalledApplication) -> None:
        self.installed: InstalledApplication | None = installed
        self.payload_disappeared: bool = False

    def installed_application(self) -> InstalledApplication | None:
        if self.payload_disappeared:
            msg = "uninstall registry InstallLocation no longer contains the EXE"
            raise RuntimeError(msg)
        return self.installed


class _FakeInstallationWatcher:
    def __init__(self, on_change: Callable[[], None], events: int = 1) -> None:
        self.on_change: Callable[[], None] = on_change
        self.events_remaining: int = events
        self.timeouts: list[int] = []
        self.closed: bool = False

    def wait_for_change(self, timeout_ms: int) -> bool:
        self.timeouts.append(timeout_ms)
        if self.events_remaining == 0:
            return False
        self.events_remaining -= 1
        self.on_change()
        return True

    def close(self) -> None:
        self.closed = True


class _FakeWatcherFactory:
    def __init__(self, watchers: Sequence[_FakeInstallationWatcher]) -> None:
        self.watchers: list[_FakeInstallationWatcher] = list(watchers)
        self.parents: list[Path] = []

    def create(self, install_parent: Path) -> _FakeInstallationWatcher:
        self.parents.append(install_parent)
        if not self.watchers:
            msg = "test did not provide an installation watcher"
            raise AssertionError(msg)
        return self.watchers.pop(0)


class _FakeNativeExecutor:
    def __init__(
        self,
        installer: Path,
        installed: InstalledApplication,
        registry: _FakeRegistry,
        *,
        publish_on_install: bool = True,
        installer_exit_code: int = 0,
    ) -> None:
        self.installer: Path = installer
        self.installed: InstalledApplication = installed
        self.registry: _FakeRegistry = registry
        self.publish_on_install: bool = publish_on_install
        self.installer_exit_code: int = installer_exit_code
        self.commands: list[tuple[str, ...]] = []
        self.working_directories: list[Path] = []
        self.timeouts: list[int] = []

    def run(self, command: Sequence[str], *, timeout_seconds: int, cwd: Path) -> int:
        self.commands.append(tuple(command))
        self.working_directories.append(cwd)
        self.timeouts.append(timeout_seconds)
        if command[0] == str(self.installer):
            if self.publish_on_install:
                self.registry.installed = self.installed
            return self.installer_exit_code
        return 0


def test_wait_for_devtools_active_port_uses_the_marker_change_event(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "EBWebView" / "DevToolsActivePort"
    changes = _FakeDirectoryChanges(
        marker,
        [None, "51234\n/devtools/browser/qa-session\n"],
    )

    port = wait_for_devtools_active_port(
        tmp_path,
        changes,
        30_000,
        clock_ms=lambda: 1_000,
    )

    assert port == 51234
    assert changes.timeouts == [30_000, 30_000]
    assert changes.closed is True


def test_wait_for_devtools_active_port_times_out_without_a_marker(
    tmp_path: Path,
) -> None:
    changes = _FakeDirectoryChanges(
        tmp_path / "EBWebView" / "DevToolsActivePort",
        [],
    )

    with pytest.raises(TimeoutError, match="did not create DevToolsActivePort"):
        _ = wait_for_devtools_active_port(
            tmp_path,
            changes,
            30_000,
            clock_ms=lambda: 1_000,
        )

    assert changes.timeouts == [30_000]
    assert changes.closed is True


def test_parse_args_accepts_documented_scenario_and_resolves_paths(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "G2B Desktop.exe"
    executable.touch()
    evidence = tmp_path / "evidence"

    options = parse_args(
        [
            "--scenario",
            "startup-catalog",
            "--exe",
            str(executable),
            "--evidence-dir",
            str(evidence),
            "--timeout-seconds",
            "45",
        ]
    )

    assert options.scenario == "startup-catalog"
    assert options.exe == executable.resolve()
    assert options.installer is None
    assert options.evidence_dir == evidence.resolve()
    assert options.timeout_seconds == 45
    assert options.cleanup_only is False


def test_parse_args_requires_installer_for_installed_parity(tmp_path: Path) -> None:
    installer = tmp_path / "G2B Compare Desktop Setup.exe"
    installer.touch()

    options = parse_args(
        [
            "--scenario",
            "installed-parity",
            "--installer",
            str(installer),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-id",
            "installed-chain",
        ]
    )

    assert options.exe is None
    assert options.installer == installer.resolve()
    assert options.run_id == "installed-chain"
    with pytest.raises(SystemExit) as raised:
        _ = parse_args(
            [
                "--scenario",
                "installed-parity",
                "--evidence-dir",
                str(tmp_path / "evidence"),
            ]
        )
    assert raised.value.code == 2


def test_installed_child_command_carries_exact_parent_provenance(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "setup.exe"
    executable = tmp_path / INSTALLED_EXECUTABLE_NAME
    installer.touch()
    executable.touch()
    options = parse_args(
        [
            "--scenario",
            "installed-parity",
            "--installer",
            str(installer),
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    provenance = InstalledChildProvenance(
        installer=installer.resolve(),
        executable=executable.resolve(),
        installer_sha256="a" * 64,
        executable_sha256="b" * 64,
        qa_harness_sha256="c" * 64,
    )

    command = installed_child_command(
        options,
        "full-parity",
        tmp_path / "child-evidence",
        provenance,
    )

    assert command[:5] == [
        sys.executable,
        str(HARNESS_SOURCE),
        "--scenario",
        "full-parity",
        "--exe",
    ]
    assert command[command.index("--installer") + 1] == str(installer.resolve())
    assert command[command.index("--expected-exe-sha256") + 1] == "b" * 64
    assert command[command.index("--expected-installer-sha256") + 1] == "a" * 64
    assert command[command.index("--qa-harness-sha256") + 1] == "c" * 64


@pytest.mark.parametrize(
    "arguments",
    [
        ["--scenario", "unknown"],
        ["--scenario", "full-parity", "--timeout-seconds", "0"],
        ["--scenario", "adversarial", "--timeout-seconds", "601"],
        ["--scenario", "startup-catalog", "--surprise"],
    ],
)
def test_parse_args_rejects_unknown_or_unbounded_values(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    executable = tmp_path / "app.exe"
    executable.touch()
    required = [
        "--exe",
        str(executable),
        "--evidence-dir",
        str(tmp_path / "evidence"),
    ]

    with pytest.raises(SystemExit) as raised:
        _ = parse_args([*arguments, *required])

    assert raised.value.code == 2


def test_parse_args_rejects_missing_or_non_executable_path(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"

    executables = (tmp_path / "missing.exe", tmp_path / "desktop.txt")
    executables[1].touch()
    for executable in executables:
        with pytest.raises(SystemExit) as raised:
            _ = parse_args(
                [
                    "--scenario",
                    "startup-catalog",
                    "--exe",
                    str(executable),
                    "--evidence-dir",
                    str(evidence),
                ]
            )
        assert raised.value.code == 2


def test_cleanup_only_keeps_strict_required_paths_but_does_not_require_exe(
    tmp_path: Path,
) -> None:
    options = parse_args(
        [
            "--scenario",
            "adversarial",
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--cleanup-only",
        ]
    )

    assert options.cleanup_only is True
    assert options.exe is None


def test_receipt_store_redacts_nested_secrets_and_writes_ordered_events(
    tmp_path: Path,
) -> None:
    store = ReceiptStore(
        tmp_path,
        ReceiptContext(
            scenario="startup-catalog",
            run_id="run-001",
            secrets=("literal-private-value",),
            clock=lambda: "2026-08-04T12:00:00Z",
        ),
    )

    _ = store.record(
        "launch",
        ReceiptStatus.PASSED,
        {
            "api_key": "literal-private-value",
            "safe": "Authorization: Bearer literal-private-value",
            "nested": {"password": "do-not-write", "count": 7},
        },
    )
    _ = store.record("catalog", ReceiptStatus.UNAVAILABLE, {"reason": "command absent"})
    summary = store.finish()

    events_path = tmp_path / "run-001" / "events.jsonl"
    summary_path = tmp_path / "run-001" / "receipt.json"
    serialized = events_path.read_text(encoding="utf-8")
    events = [
        require_mapping(cast("object", json.loads(line)), "event")
        for line in serialized.splitlines()
    ]
    written_summary = require_mapping(
        cast("object", json.loads(summary_path.read_text(encoding="utf-8"))),
        "summary",
    )
    first_details = require_mapping(events[0]["details"], "event details")
    nested = require_mapping(first_details["nested"], "nested details")

    assert "literal-private-value" not in serialized
    assert "do-not-write" not in serialized
    assert events[0]["sequence"] == 1
    assert first_details["api_key"] == "[REDACTED]"
    assert nested["password"] == "[REDACTED]"
    assert events[1]["sequence"] == 2
    assert summary == written_summary
    assert summary["outcome"] == "unavailable"
    assert summary["counts"] == {"failed": 0, "passed": 1, "unavailable": 1}
    assert summary["qa_harness_sha256"] == sha256_file(HARNESS_SOURCE)


def test_post_chain_integrity_adds_sixth_passing_check_after_cleanup(
    tmp_path: Path,
) -> None:
    state, installer, _ = _post_chain_receipt_state(tmp_path)

    record_post_chain_integrity(state, installer)

    assert len(state.events) == 6
    check = state.events[-1]
    details = require_mapping(check["details"], "post-chain integrity details")
    children = require_mapping_list(details["children"], "post-chain children")
    qa_harness_source = require_mapping(
        details["qa_harness_source"], "post-chain harness source"
    )
    assert check["sequence"] == 6
    assert check["check"] == "post-chain-provenance-integrity"
    assert check["status"] == ReceiptStatus.PASSED.value
    assert details["installer"] == {
        "bytes": installer.stat().st_size,
        "sha256": sha256_file(installer),
    }
    assert qa_harness_source["sha256"] == sha256_file(HARNESS_SOURCE)
    assert [child["scenario"] for child in children] == [
        "full-parity",
        "adversarial",
    ]
    assert details["cleanup_flags"] == {
        "directory_removed": True,
        "registry_removed": True,
        "process_cleanup": True,
        "ports_closed": True,
    }


def test_post_chain_integrity_fails_for_a_tampered_child_receipt(
    tmp_path: Path,
) -> None:
    state, installer, child_receipts = _post_chain_receipt_state(tmp_path)
    receipt_path = child_receipts["full-parity"]
    receipt = require_mapping(
        cast("object", json.loads(receipt_path.read_text(encoding="utf-8"))),
        "child receipt",
    )
    receipt["outcome"] = ReceiptStatus.FAILED.value
    _ = receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    record_post_chain_integrity(state, installer)

    check = state.events[-1]
    details = require_mapping(check["details"], "post-chain integrity details")
    assert check["status"] == ReceiptStatus.FAILED.value
    assert "child receipt hash did not match" in str(details["error"])


def test_post_chain_integrity_fails_for_a_tampered_installer(
    tmp_path: Path,
) -> None:
    state, installer, _ = _post_chain_receipt_state(tmp_path)
    _ = installer.write_bytes(b"tampered")

    record_post_chain_integrity(state, installer)

    check = state.events[-1]
    details = require_mapping(check["details"], "post-chain integrity details")
    assert check["status"] == ReceiptStatus.FAILED.value
    assert "installer bytes changed" in str(details["error"])


def test_receipt_rejects_a_parent_source_hash_mismatch(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="does not match its parent hash"):
        _ = ReceiptStore(
            tmp_path,
            ReceiptContext(
                scenario="full-parity",
                run_id="wrong-source",
                expected_qa_harness_sha256="0" * 64,
            ),
        )


def test_receipt_failure_controls_outcome_and_artifacts_are_relative(
    tmp_path: Path,
) -> None:
    store = ReceiptStore(
        tmp_path,
        ReceiptContext(
            scenario="adversarial",
            run_id="run-002",
            clock=lambda: "2026-08-04T12:00:00Z",
        ),
    )
    screenshot = store.artifact_path("screenshots", "bad-input.png")
    _ = screenshot.write_bytes(b"png")

    _ = store.record(
        "bad-input",
        ReceiptStatus.FAILED,
        {"artifact": store.relative_artifact(screenshot)},
    )
    summary = store.finish()

    events = require_mapping_list(summary["events"], "summary events")
    details = require_mapping(events[0]["details"], "event details")
    assert summary["outcome"] == "failed"
    assert details["artifact"] == "screenshots/bad-input.png"
    with pytest.raises(ValueError, match="outside the run evidence directory"):
        _ = store.relative_artifact(tmp_path.parent / "other.png")


def test_registry_install_location_resolves_only_the_installed_executable(
    tmp_path: Path,
) -> None:
    install_location = tmp_path / "installed application"
    install_location.mkdir()
    executable = install_location / INSTALLED_EXECUTABLE_NAME
    uninstaller = install_location / "uninstall.exe"
    executable.touch()
    uninstaller.touch()

    installed = installed_application_from_registry_values(
        {
            "InstallLocation": f'"{install_location}"',
            "UninstallString": f'"{uninstaller}"',
        }
    )

    assert installed.install_location == install_location.resolve()
    assert installed.executable == executable.resolve()
    assert installed.uninstaller == uninstaller.resolve()


def test_wait_for_install_completion_uses_delayed_registry_event(
    tmp_path: Path,
) -> None:
    install_location = tmp_path / "installed application"
    install_location.mkdir()
    executable = install_location / INSTALLED_EXECUTABLE_NAME
    uninstaller = install_location / "uninstall.exe"
    executable.touch()
    uninstaller.touch()
    installed = InstalledApplication(install_location, executable, uninstaller)
    registry = _FakeRegistry()
    watcher = _FakeInstallationWatcher(
        lambda: setattr(registry, "installed", installed)
    )

    resolved = wait_for_install_completion(
        registry,
        watcher,
        30_000,
        clock_ms=lambda: 1_000,
    )

    assert resolved == installed
    assert watcher.timeouts == [30_000]


def test_uninstall_wait_treats_removed_executable_as_a_transitional_state(
    tmp_path: Path,
) -> None:
    install_location = tmp_path / "installed application"
    install_location.mkdir()
    executable = install_location / INSTALLED_EXECUTABLE_NAME
    uninstaller = install_location / "uninstall.exe"
    executable.touch()
    uninstaller.touch()
    installed = InstalledApplication(install_location, executable, uninstaller)
    registry = _FakePayloadDisappearingRegistry(installed)

    def advance_uninstall() -> None:
        if not registry.payload_disappeared:
            executable.unlink()
            registry.payload_disappeared = True
            return
        registry.installed = None
        registry.payload_disappeared = False
        shutil.rmtree(install_location)

    watcher = _FakeInstallationWatcher(advance_uninstall, events=2)

    wait_for_uninstall_completion(
        installed,
        registry,
        watcher,
        30_000,
        clock_ms=lambda: 1_000,
    )

    assert watcher.timeouts == [30_000, 30_000]
    assert registry.installed_application() is None
    assert not install_location.exists()


def test_installer_chain_uses_exact_silent_commands_and_evented_cleanup(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "setup.exe"
    installer.touch()
    install_location = tmp_path / "installed application"
    install_location.mkdir()
    executable = install_location / INSTALLED_EXECUTABLE_NAME
    uninstaller = install_location / "uninstall.exe"
    executable.touch()
    uninstaller.touch()
    installed = InstalledApplication(
        install_location=install_location,
        executable=executable,
        uninstaller=uninstaller,
    )
    registry = _FakeRegistry()

    def complete_uninstall() -> None:
        registry.installed = None
        shutil.rmtree(install_location)

    install_watcher = _FakeInstallationWatcher(lambda: None)
    uninstall_watcher = _FakeInstallationWatcher(complete_uninstall)
    watchers = _FakeWatcherFactory([install_watcher, uninstall_watcher])
    executor = _FakeNativeExecutor(installer, installed, registry)
    chain = InstallerChain(installer, 30, registry, executor, watchers)

    chain.preflight_clean_state()
    resolved, install_exit = chain.install()
    uninstall_exit = chain.uninstall(resolved)

    assert install_exit == 0
    assert uninstall_exit == 0
    assert executor.commands == [
        (str(installer), "/S"),
        (str(uninstaller), "/S"),
    ]
    assert executor.working_directories == [installer.parent, uninstaller.parent]
    assert executor.timeouts == [30, 30]
    assert len(watchers.parents) == 2
    assert watchers.parents[1] == install_location.parent
    assert install_watcher.timeouts == []
    assert install_watcher.closed is True
    assert uninstall_watcher.timeouts == [30_000]
    assert uninstall_watcher.closed is True
    assert registry.installed_application() is None
    assert not install_location.exists()


def test_installer_chain_fails_closed_when_the_uninstall_entry_exists(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "setup.exe"
    installer.touch()
    existing = InstalledApplication(
        install_location=tmp_path / "existing",
        executable=tmp_path / "existing" / INSTALLED_EXECUTABLE_NAME,
        uninstaller=tmp_path / "existing" / "uninstall.exe",
    )
    registry = _FakeRegistry(existing)
    watcher = _FakeInstallationWatcher(lambda: None)
    executor = _FakeNativeExecutor(installer, existing, registry)
    chain = InstallerChain(
        installer,
        30,
        registry,
        executor,
        _FakeWatcherFactory([watcher]),
    )

    with pytest.raises(RuntimeError, match="already names an app"):
        chain.preflight_clean_state()

    assert executor.commands == []
    assert watcher.timeouts == []


def test_failed_installer_chain_late_resolves_and_uninstalls(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "setup.exe"
    installer.touch()
    install_location = tmp_path / "installed application"
    install_location.mkdir()
    executable = install_location / INSTALLED_EXECUTABLE_NAME
    uninstaller = install_location / "uninstall.exe"
    executable.touch()
    uninstaller.touch()
    installed = InstalledApplication(install_location, executable, uninstaller)
    registry = _FakeRegistry()

    def complete_uninstall() -> None:
        registry.installed = None
        shutil.rmtree(install_location)

    primary_watcher = _FakeInstallationWatcher(lambda: None, events=0)
    late_watcher = _FakeInstallationWatcher(lambda: None)
    uninstall_watcher = _FakeInstallationWatcher(complete_uninstall)
    watchers = _FakeWatcherFactory([primary_watcher, late_watcher, uninstall_watcher])
    executor = _FakeNativeExecutor(
        installer,
        installed,
        registry,
        publish_on_install=False,
    )
    chain = InstallerChain(installer, 30, registry, executor, watchers)

    with pytest.raises(TimeoutError, match="complete authoritative HKCU"):
        _ = chain.install()
    registry.installed = installed
    late_installed = chain.late_resolve_installation()
    assert late_installed is not None
    assert late_installed == installed
    assert chain.uninstall(late_installed) == 0

    assert executor.commands == [
        (str(installer), "/S"),
        (str(uninstaller), "/S"),
    ]
    assert primary_watcher.closed is True
    assert late_watcher.closed is True
    assert uninstall_watcher.closed is True
    assert registry.installed_application() is None
    assert not install_location.exists()


def test_installed_parity_cleans_a_validated_app_published_before_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = tmp_path / "setup.exe"
    _ = installer.write_bytes(b"installer")
    install_location = tmp_path / "installed application"
    install_location.mkdir()
    executable = install_location / INSTALLED_EXECUTABLE_NAME
    uninstaller = install_location / "uninstall.exe"
    executable.touch()
    uninstaller.touch()
    installed = installed_application_from_registry_values(
        {
            "InstallLocation": f'"{install_location}"',
            "UninstallString": f'"{uninstaller}"',
        }
    )
    registry = _FakeRegistry()

    def complete_uninstall() -> None:
        registry.installed = None
        shutil.rmtree(install_location)

    install_watcher = _FakeInstallationWatcher(lambda: None)
    late_watcher = _FakeInstallationWatcher(lambda: None)
    uninstall_watcher = _FakeInstallationWatcher(complete_uninstall)
    watchers = _FakeWatcherFactory([install_watcher, late_watcher, uninstall_watcher])
    executor = _FakeNativeExecutor(
        installer,
        installed,
        registry,
        installer_exit_code=1,
    )
    options = parse_args(
        [
            "--scenario",
            "installed-parity",
            "--installer",
            str(installer),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-id",
            "nonzero-published",
            "--timeout-seconds",
            "30",
        ]
    )
    monkeypatch.setattr(tauri_desktop_qa, "WindowsUninstallRegistry", lambda: registry)
    monkeypatch.setattr(
        tauri_desktop_qa, "WindowsNativeCommandExecutor", lambda: executor
    )
    monkeypatch.setattr(
        tauri_desktop_qa,
        "WindowsInstallationCompletionWatcherFactory",
        lambda: watchers,
    )
    monkeypatch.setattr(
        tauri_desktop_qa, "current_user_install_parent", lambda: tmp_path
    )

    assert run_installed_parity(options) == 1

    receipt_path = tmp_path / "evidence" / "nonzero-published" / "install-receipt.json"
    receipt = require_mapping(
        cast("object", json.loads(receipt_path.read_text(encoding="utf-8"))),
        "installed-parity receipt",
    )
    chain = require_mapping_list(receipt["chain"], "installed-parity chain")
    installer_details = require_mapping(receipt["installer"], "installer details")
    cleanup = require_mapping(receipt["cleanup"], "cleanup details")
    installer_failure = next(
        event for event in chain if event["check"] == "installed-parity-chain"
    )
    cleanup_event = next(
        event for event in chain if event["check"] == "silent-uninstall-evented-cleanup"
    )

    assert receipt["outcome"] == ReceiptStatus.FAILED.value
    assert installer_details["exit_code"] == 1
    assert installer_failure["status"] == ReceiptStatus.FAILED.value
    assert installer_failure["details"] == {
        "error": "NSIS installer exited with code 1",
        "error_type": "RuntimeError",
    }
    assert cleanup_event["status"] == ReceiptStatus.PASSED.value
    assert cleanup["uninstaller_command"] == [str(uninstaller), "/S"]
    assert cleanup["uninstaller_exit_code"] == 0
    assert cleanup["directory_removed"] is True
    assert cleanup["registry_removed"] is True
    assert executor.commands == [
        (str(installer), "/S"),
        (str(uninstaller), "/S"),
    ]
    assert install_watcher.timeouts == []
    assert late_watcher.timeouts == []
    assert uninstall_watcher.timeouts == [30_000]
    assert registry.installed_application() is None
    assert not install_location.exists()


def test_installed_parity_nonzero_without_an_app_skips_destructive_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = tmp_path / "setup.exe"
    _ = installer.write_bytes(b"installer")
    install_location = tmp_path / "unpublished application"
    installed = InstalledApplication(
        install_location,
        install_location / INSTALLED_EXECUTABLE_NAME,
        install_location / "uninstall.exe",
    )
    registry = _FakeRegistry()
    install_watcher = _FakeInstallationWatcher(lambda: None)
    late_watcher = _FakeInstallationWatcher(lambda: None, events=0)
    watchers = _FakeWatcherFactory([install_watcher, late_watcher])
    executor = _FakeNativeExecutor(
        installer,
        installed,
        registry,
        publish_on_install=False,
        installer_exit_code=1,
    )
    options = parse_args(
        [
            "--scenario",
            "installed-parity",
            "--installer",
            str(installer),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-id",
            "nonzero-empty",
            "--timeout-seconds",
            "30",
        ]
    )
    monkeypatch.setattr(tauri_desktop_qa, "WindowsUninstallRegistry", lambda: registry)
    monkeypatch.setattr(
        tauri_desktop_qa, "WindowsNativeCommandExecutor", lambda: executor
    )
    monkeypatch.setattr(
        tauri_desktop_qa,
        "WindowsInstallationCompletionWatcherFactory",
        lambda: watchers,
    )
    monkeypatch.setattr(
        tauri_desktop_qa, "current_user_install_parent", lambda: tmp_path
    )

    assert run_installed_parity(options) == 1

    receipt_path = tmp_path / "evidence" / "nonzero-empty" / "install-receipt.json"
    receipt = require_mapping(
        cast("object", json.loads(receipt_path.read_text(encoding="utf-8"))),
        "installed-parity receipt",
    )
    chain = require_mapping_list(receipt["chain"], "installed-parity chain")
    cleanup = require_mapping(receipt["cleanup"], "cleanup details")
    installer_failure = next(
        event for event in chain if event["check"] == "installed-parity-chain"
    )
    cleanup_event = next(
        event for event in chain if event["check"] == "silent-uninstall-evented-cleanup"
    )

    assert receipt["outcome"] == ReceiptStatus.FAILED.value
    assert installer_failure["details"] == {
        "error": "NSIS installer exited with code 1",
        "error_type": "RuntimeError",
    }
    assert cleanup_event["details"] == {
        "error": "installer did not yield a validated installed app"
    }
    assert "uninstaller_command" not in cleanup
    assert executor.commands == [(str(installer), "/S")]
    assert install_watcher.timeouts == []
    assert late_watcher.timeouts == [30_000]
    assert install_watcher.closed is True
    assert late_watcher.closed is True
    assert registry.installed_application() is None
    assert not install_location.exists()


def test_qa_replay_injection_writes_one_valid_deterministic_create_mutation(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "qa-state"
    replay_database = state_root / "app-data" / "offline-replay.sqlite3"
    replay_database.parent.mkdir(parents=True)
    unrelated_user_database = tmp_path / "user-data" / "g2b.sqlite3"
    unrelated_user_database.parent.mkdir()
    _ = unrelated_user_database.write_bytes(b"production-user-data-must-not-change")

    with sqlite3.connect(replay_database) as connection:
        _ = connection.executescript(
            """
            CREATE TABLE offline_replay_mutations (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT CHECK (sequence > 0),
                entity_id TEXT NOT NULL,
                payload BLOB NOT NULL
            ) STRICT;
            CREATE TABLE offline_replay_conflicts (
                sequence INTEGER PRIMARY KEY
                    REFERENCES offline_replay_mutations(sequence) ON DELETE CASCADE,
                entity_id TEXT NOT NULL,
                reason_code TEXT NOT NULL
            ) STRICT;
            """
        )

    sequence = inject_qa_replay_mutation(state_root)

    with sqlite3.connect(replay_database) as connection:
        row = cast(
            "tuple[int, str, bytes] | None",
            connection.execute(
                "SELECT sequence, entity_id, payload FROM offline_replay_mutations"
            ).fetchone(),
        )
    assert row is not None
    payload = require_mapping(
        cast("object", json.loads(row[2])),
        "payload",
    )
    request = require_mapping(payload["request"], "create request")
    lines = require_mapping_list(request["lines"], "create lines")

    assert sequence == 1
    assert row[0] == 1
    assert row[1] == QA_REPLAY_ESTIMATE_ID
    assert payload["operation"] == "create_estimate"
    assert request["id"] == QA_REPLAY_ESTIMATE_ID
    assert request["title"] == "QA offline replay estimate"
    assert request["comparisons"] == []
    assert lines == [
        {
            "company_snapshot": "QA replay company",
            "id": QA_REPLAY_LINE_ID,
            "item_name_snapshot": "QA replay item",
            "line_kind": "main",
            "offer_key": None,
            "offer_operation": None,
            "parent_product_id": None,
            "product_id": "24492324",
            "quantity": "1",
            "relation_id": None,
            "spec_snapshot": "QA replay specification",
            "unit_price_won_snapshot": 1000,
            "unit_snapshot": "EA",
        }
    ]
    assert (
        unrelated_user_database.read_bytes() == b"production-user-data-must-not-change"
    )


def test_qa_replay_injection_rejects_a_missing_isolated_queue(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="isolated QA replay database"):
        _ = inject_qa_replay_mutation(tmp_path / "qa-state")
