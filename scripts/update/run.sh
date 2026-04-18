#!/bin/bash
#
# Full update pipeline (Unix): project, cache, data ETL, builder test/export,
# aggregate JSON, pytest.
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$SCRIPT_DIR/1_project.sh"
bash "$SCRIPT_DIR/2_cache.sh"
bash "$SCRIPT_DIR/3_data.sh"
bash "$SCRIPT_DIR/4_builders_test.sh"
bash "$SCRIPT_DIR/5_builders_run.sh"
bash "$SCRIPT_DIR/6_update.sh"
