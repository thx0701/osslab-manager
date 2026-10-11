#!/bin/bash
# Fixture route: --model fixture/codex -c model_reasoning_effort=medium
set -eu
cd "$1"
case "$(cat "$2")" in
  empty) exit 0 ;;
  fail) exit 2 ;;
  mutate) echo bad > source.txt ;;
esac
printf 'Fixture Codex review: manager must inspect findings.\n'
