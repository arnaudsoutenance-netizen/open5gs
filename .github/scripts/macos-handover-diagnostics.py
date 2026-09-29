#!/usr/bin/env python3
"""Run the full Meson suite and sample a long-running macOS handover process.

Diagnostic collection is best effort. Only Meson's exit status determines
success; no retries, skipped tests, or changes to the existing -t 3 timeout.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def process_table():
    """Return {pid: (ppid, command)} without exposing process environments."""
    result = subprocess.run(
        ["ps", "-ww", "-axo", "pid=,ppid=,command="],
        check=True, stdout=subprocess.PIPE, text=True, timeout=5,
    )
    table = {}
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            table[int(fields[0])] = (int(fields[1]), fields[2])
    return table


def descendants(table, parent):
    found = {parent}
    while True:
        added = {pid for pid, (ppid, _) in table.items() if ppid in found} - found
        if not added:
            return found - {parent}
        found.update(added)


def capture(table, root, output):
    """Start bounded samplers before Meson can terminate the hung test."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "processes.txt").write_text(
        "".join(f"{pid} {ppid} {cmd}\n" for pid, (ppid, cmd) in sorted(table.items()))
    )
    # Refresh once before attaching, before any sampler has been launched.
    current = process_table()
    if current.get(root) != table.get(root):
        return []
    children = descendants(current, root)
    targets = [root] + sorted(descendants(table, root))
    jobs = []
    for pid in targets:
        if current.get(pid) != table.get(pid):
            continue
        if pid != root and pid not in children:
            continue
        log = (output / f"sample-{pid}.log").open("w")
        try:
            job = subprocess.Popen(
                ["/usr/bin/sample", str(pid), "2", "1", "-file",
                 str(output / f"sample-{pid}.txt")],
                stdout=log, stderr=subprocess.STDOUT,
            )
        except OSError as error:
            print(f"[HO-DIAG] sample {pid} unavailable: {error}", flush=True)
        else:
            jobs.append((job, time.monotonic()))
        finally:
            log.close()
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("meson", help="absolute path to the Meson executable")
    args = parser.parse_args()
    build = args.build.resolve()
    output = build / "macos-handover-diagnostics"
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[2] / "tests" / "handover"
    for name in ("abts-main.c", "5gc-n2-test.c"):
        try:
            shutil.copyfile(source / name, output / name)
        except OSError as error:
            print(f"[HO-DIAG] cannot save {name}: {error}", flush=True)

    env = os.environ.copy()
    env["OGS_HO_DIAGNOSTICS"] = "1"
    command = [args.meson, "test", "-C", str(build), "-v", "-t", "3",
               "--test-args=-d"]
    print(f"[HO-DIAG] command: {command!r}", flush=True)
    print("[HO-DIAG] sampling at handover age 30s; Meson timeout unchanged", flush=True)
    test = subprocess.Popen(command, env=env)
    executable = str(build / "tests" / "handover" / "handover")
    first_seen = {}
    sampled = set()
    samples = []
    monitoring = sys.platform == "darwin"

    while test.poll() is None:
        if monitoring:
            try:
                table = process_table()
                related = descendants(table, test.pid)
                for pid in related:
                    cmd = table[pid][1]
                    if cmd != executable and not cmd.startswith(executable + " "):
                        continue
                    first_seen.setdefault(pid, time.monotonic())
                    if pid not in sampled and time.monotonic() - first_seen[pid] >= 30:
                        sampled.add(pid)
                        print(f"[HO-DIAG] sampling handover pid={pid} and children", flush=True)
                        jobs = capture(table, pid, output / f"handover-{pid}")
                        samples.extend(jobs)
            except (OSError, subprocess.SubprocessError) as error:
                # Do not turn a diagnostic-tool problem into a test result.
                print(f"[HO-DIAG] monitoring disabled: {error}", flush=True)
                monitoring = False
        for job, started in samples:
            if job.poll() is None and time.monotonic() - started >= 10:
                print(f"[HO-DIAG] stopping stalled sampler pid={job.pid}", flush=True)
                job.kill()
                job.wait()
        time.sleep(1)

    for job, _ in samples:
        if job.poll() is None:
            try:
                job.wait(timeout=3)
            except subprocess.TimeoutExpired:
                job.kill()
                job.wait()
    result = test.wait()
    print(f"[HO-DIAG] Meson exit status: {result}", flush=True)
    return result if result >= 0 else 128 - result


if __name__ == "__main__":
    sys.exit(main())
