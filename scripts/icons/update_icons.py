 
from pathlib import Path
from osrsreboxed import items_api

import multiprocessing as mp
import hashlib
import config
import requests
import json

RUNELITE_ICON_URL = "https://static.runelite.net/cache/item/icon/"
BLANK = "bb44d26003a2b044e235aae2fc8427f7"
ICONS_PATH = config.DOCS_PATH / "items-icons"

def get_md5(file_path):
    h = hashlib.new("md5")
    with open(file_path, "rb") as file:
        block = file.read(512)
        while block:
            h.update(block)
            block = file.read(512)

    return h.hexdigest()

def main():            
    all_db_items = [item for item in items_api.load()]
    item_ids = [item.id for item in all_db_items]
    noted_ids = [item.linked_id_noted for item in all_db_items if item.linked_id_noted ]
    icon_ids = sorted(item_ids + noted_ids)
    with mp.Pool(processes=16) as pool:
        pool.starmap(fetch_icon, [(item_id, ICONS_PATH) for item_id in icon_ids])
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
