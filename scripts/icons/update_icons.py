from pathlib import Path

import multiprocessing as mp
import hashlib
import logging
import json
import config
import requests
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

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
    # Load items from cache data to get all items including new ones
    cache_data_path = Path(config.DATA_ITEMS_PATH / "items-cache-data.json")
    with open(cache_data_path) as f:
        cache_data = json.load(f)

    # Collect all item IDs and their noted variants
    icon_ids = set()
    for item_id, item_data in cache_data.items():
        icon_ids.add(int(item_id))

        # Add linked_id_noted if it exists
        linked_id_noted = item_data.get("linked_id_noted")
        if linked_id_noted:
            icon_ids.add(linked_id_noted)

    icon_ids = sorted(list(icon_ids))
    logger.info(f"Fetching icons for {len(icon_ids)} items")
    with mp.Pool(processes=16) as pool:
        pool.starmap(fetch_icon, [(item_id, ICONS_PATH) for item_id in icon_ids])
    logger.info("Done")
    exit(0)


def fetch_icon(item_id, dir_path):
    file_name = f"{item_id}" + ".png"
    file_path = dir_path / file_name
    if file_path.is_file():
        return
    logger.debug(f"Fetching icon {item_id}")
    target_url = RUNELITE_ICON_URL + file_name

    try:
        resp = requests.get(target_url, stream=True, timeout=15)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed icon request for {item_id}: {e}")
        return

    # Only accept successful responses
    if resp.status_code != 200:
        logger.warning(f"Skipping {item_id}: HTTP {resp.status_code}")
        return

    # Content-Type header should indicate an image (png)
    ctype = resp.headers.get("Content-Type", "")
    if not ctype.startswith("image/"):
        # Sometimes a HTML error page is returned instead of an image
        logger.warning(f"Skipping {item_id}: unexpected Content-Type: {ctype}")
        return

    # Stream to a temp file first to avoid writing invalid content
    tmp_path = dir_path / (file_name + ".tmp")
    try:
        with open(tmp_path, "wb") as out_file:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    out_file.write(chunk)
    except OSError as e:
        logger.error(f"Failed to write icon {item_id}: {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return

    # Quick sanity check: PNG files start with the PNG signature
    try:
        with open(tmp_path, "rb") as f:
            sig = f.read(8)
    except OSError:
        logger.error(f"Failed to read tmp file for {item_id}")
        try:
            tmp_path.unlink()
        except Exception:
            pass
        return

    if not sig.startswith(b"\x89PNG\r\n\x1a\n"):
        # Not a PNG (could be HTML or other); skip and remove tmp
        logger.warning(
            f"Skipping {item_id}: downloaded file is not a PNG (signature mismatch)"
        )
        try:
            tmp_path.unlink()
        except Exception:
            pass
        return

    # Move tmp file to final location
    try:
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            os.rename(tmp_path, file_path)
        except Exception as e:
            logger.error(f"Failed to move tmp file into place for {item_id}: {e}")
            try:
                tmp_path.unlink()
            except Exception:
                pass
            return

    # Remove blank placeholder icons
    md5 = get_md5(file_path)
    if md5 == BLANK:
        try:
            file_path.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
