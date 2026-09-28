#!/bin/bash
# Fixture route: ZCODE_MODEL=fixture-glm
exec bash "$(dirname "$0")/pi-openrouter-worker.sh" "$@"
