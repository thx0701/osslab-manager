#!/bin/bash
# Fixture route: --model fixture/grok --reasoning-effort medium
set -eu
cd "$1"
case "$(cat "$2")" in
  empty) exit 0 ;;
  fail) exit 2 ;;
  mutate) echo bad > source.txt ;;
esac
printf 'Fixture review: inspect source and require manager judgment.\n'
