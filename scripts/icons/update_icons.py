 
from pathlib import Path

import multiprocessing as mp
import hashlib
import config
import requests
import json

RUNELITE_ICON_URL = "https://static.runelite.net/cache/item/icon/"
BLANK = "bb44d26003a2b044e235aae2fc8427f7"

def get_md5(file_path):
    h = hashlib.new("md5")
    with open(file_path, "rb") as file:
        block = file.read(512)
        while block:
            h.update(block)
            block = file.read(512)

    return h.hexdigest()

def main():
    items_dir = config.DATA_CACHE_PATH / "item_defs"
    item_files = Path(items_dir).glob("*.json")
    icons_path = config.DOCS_PATH / "items-icons"

    # Filter out placeholderId item_ids (null name, negative notedID)
    filtered_ids = []
    for file in item_files:
        item_id = file.stem 
        item_defs_path = items_dir / f"{item_id}.json"
        if item_defs_path.is_file():
            try:
                with open(item_defs_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("name", "null") == "null" and data.get("notedID", 0) < 0:
                        continue
                filtered_ids.append(item_id)
            except Exception:
                pass
            
    filtered_ids = sorted(filtered_ids)

    with mp.Pool(processes=16) as pool:
        pool.starmap(fetch_icon, [(item_id, icons_path) for item_id in filtered_ids])

    print("Done")
    exit(0)

def fetch_icon(item_id, dir_path):
    file_name = f"{item_id}" + ".png"
    file_path = dir_path / file_name
    if file_path.is_file():
        return

    print(f"> Fetching icon {item_id}")
    target_url = RUNELITE_ICON_URL + file_name
    try:
        with open(file_path, 'wb') as out_file:
            content = requests.get(target_url, stream=True).content
            out_file.write(content)
    except(ConnectionError):
        print("Failed icon request")
        return

    md5 = get_md5(file_path)
    if md5 == BLANK:
        file_path.unlink()


if __name__ == "__main__":
    main()
