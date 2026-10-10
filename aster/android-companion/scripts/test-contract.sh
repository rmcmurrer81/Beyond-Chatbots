#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
java -m jdk.compiler/com.sun.tools.javac.Main -source 17 -target 17 -d "$out" app/src/main/java/dev/aster/companion/InvitationGate.java app/src/test/java/dev/aster/companion/InvitationGateTest.java
java -cp "$out" dev.aster.companion.InvitationGateTest
