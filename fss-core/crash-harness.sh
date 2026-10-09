#!/usr/bin/env bash
# Runs the J1 crash harness: (a) SIGKILL under load, (b) truncation at every byte offset,
# (c) bit flips. Prints a markdown results table and exits non-zero on any failure.
# Options are passed through; see CrashHarness.java (e.g. --tests a --dir /path --kill-chains 40).
set -euo pipefail
cd "$(dirname "$0")"
mvn -q -B -DskipTests test-compile
exec java -cp target/classes:target/test-classes fss.core.crash.CrashHarness "$@"
