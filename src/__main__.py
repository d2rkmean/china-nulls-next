from .utils import logging
import json
from loguru import logger
from .utils.downloader import AssetsDownloader
from pathlib import Path

def main() -> int:
    print("\nWelcome to China Nulls Next builder!\n")

    # ----------- Preparation ----------- #
    logging.console.rule("Preparation...")
    bsc_cache = Path("cache/bsc")
    bs_cache = Path("cache/bs")
    downloader = AssetsDownloader(
        bsc_fingerprint="419d27d4f07a8080418907061ebda3319ec9dd07"
    )

    # ----------- Downloading files ----------- #
    logging.console.rule("Downloading files...")
    downloader.download("fingerprint.json", server="bsc", directory=bsc_cache)
    downloader.download("fingerprint.json", server="bs", directory=bs_cache)

    with open(bsc_cache / "fingerprint.json", "r") as file:
        bsc_fingerprint: dict[str, list[dict[str, str]]] = json.load(file)

    with open(bs_cache / "fingerprint.json", "r") as file:
        bs_fingerprint: dict[str, list[dict[str, str]]]  = json.load(file)

    logger.info("Downloading CSV...")
    templist = []
    for file in bs_fingerprint["files"]:
        if file["file"].endswith(".csv"):
            templist.append(file["file"])
    downloader.download(*templist, server="bs", directory=bs_cache)
    del templist

    templist = []
    for file in bsc_fingerprint["files"]:
        if file["file"].endswith(".csv"):
            templist.append(file["file"])
    downloader.download(*templist, server="bsc", directory=bsc_cache)
    del templist

    # TODO: finish writing the generation logic 
    raise NotImplementedError()

    logging.console.rule("[bold] Сompletion ")
    return 0


if __name__ == "__main__":
    try:
        main()
        logger.success("The operation completed :3")
    except Exception as e:
        logger.exception(f"An error occurred: {e}\n")