#!/bin/bash
: '
Author:  PH01L
Email:   phoil@osrsbox.com
Website: https://www.osrsbox.com

Export builders to docs/: items with --export --validate, monsters with --export only.

Copyright (c) 2021, PH01L

###############################################################################
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
###############################################################################
'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
odb="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1090
. "$SCRIPT_DIR/_common.sh"

export PYTHONPATH="$odb"

cd "$odb" || exit 1
bootstrap="$(osrsbox_bootstrap_python)" || exit 1
"$bootstrap" -m venv venv
osrsbox_activate_venv "$odb" || exit 1

echo -e ">>> Updating item database"
mkdir -p "$odb/docs/items-json"
rm -f "$odb/docs/items-json/"*

cd "$odb/builders/items/" || exit 1
python -m builders.items.builder --export --validate

echo -e ">>> Updating monster database"
mkdir -p "$odb/docs/monsters-json"
rm -f "$odb/docs/monsters-json/"*

cd "$odb/builders/monsters/" || exit 1
python -m builders.monsters.builder --export
