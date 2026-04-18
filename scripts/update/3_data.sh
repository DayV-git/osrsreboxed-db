#!/bin/bash
: '
Author:  PH01L
Email:   phoil@osrsbox.com
Website: https://www.osrsbox.com

Process cache data, then fetch wiki data (items, monsters, shops) and icons.

Copyright (c) 2020, PH01L

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

echo -e ">>> Updating project data..."
cd "$odb" || exit 1
bootstrap="$(osrsbox_bootstrap_python)" || exit 1
"$bootstrap" -m venv venv
osrsbox_activate_venv "$odb" || exit 1

pip install -r requirements.txt

echo -e "  > cache..."
python -m scripts.cache.update

echo -e "  > items..."
python -m scripts.items.update
python -m scripts.icons.update_icons
python -m scripts.icons.convert_item_icons

echo -e "  > monsters..."
python -m scripts.monsters.update

echo -e "  > shops..."
python -m scripts.shops.update
