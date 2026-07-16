from pathlib import Path
import socket
import struct
import zlib
import json
from typing import Literal, Optional

import httpx
from loguru import logger
import logging

from rich.logging import RichHandler
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TextColumn,
)


CLIENT_HELLO_ID = 10100
LOGIN_FAILED_ID = 0x4E87
HELLO_VERSION = 0
PATCH_NAMESPACE = "com.supercell.brawlstars"


class AssetsDownloader:
    "downloads files from Brawl Stars servers"

    def __init__(self,
                 bs_path: str = "http://game-assets.brawlstarsgame.com",
                 bsc_path: str = "http://game-assets.tencent-cloud.com/",
                 bs_fingerprint: str = None,
                 bsc_fingerprint: str = None):
        self.bs_path = bs_path
        self.bsc_path = bsc_path
        self.bs_fingerprint = bs_fingerprint or self._get_fingerprint("62.233.36.83").get("sha") or None
        self.bsc_fingerprint = bsc_fingerprint or self._get_fingerprint("stage.brawlstars.cn") or None

    def download(
        self,
        *files: str,
        server: Literal["bs", "bsc"] = "bs",
        timeout: float = 30.0,
        directory: Path = Path("cache"),
    ) -> None:
        """Download one or more asset files."""

        if server == "bs":
            base_url = self.bs_path
            fingerprint = self.bs_fingerprint
        else:
            base_url = self.bsc_path
            fingerprint = self.bsc_fingerprint

        if fingerprint is None:
            raise RuntimeError(f"No fingerprint available for server '{server}'.")

        with (
            httpx.Client(timeout=timeout, follow_redirects=True) as client,
            Progress(
                TextColumn("[bold blue]{task.fields[file]}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ) as progress,
        ):
            for file in files:
                url = f"{base_url.rstrip('/')}/{fingerprint}/{file}"

                logger.info("Downloading {}", file)

                path = directory / file
                path.parent.mkdir(parents=True, exist_ok=True)

                with client.stream("GET", url) as response:
                    response.raise_for_status()

                    total = int(response.headers.get("Content-Length", 0))

                    task = progress.add_task(
                        "download",
                        file=file,
                        total=total or None,
                    )

                    with path.open("wb") as fp:
                        for chunk in response.iter_bytes(1024 * 64):
                            fp.write(chunk)
                            progress.update(
                                task,
                                advance=len(chunk),
                            )

                    progress.remove_task(task)

                logger.success(
                    "Downloaded {} ({})",
                    file,
                    path.stat().st_size,
                )
    @staticmethod
    def _write_sc_string(buf: bytearray, value: Optional[str]):
        if value is None:
            buf += struct.pack(">i", -1)
        else:
            data = value.encode("utf-8")
            buf += struct.pack(">i", len(data)) 
            buf += data

    @staticmethod
    def _build_client_hello_body(major: int, revision: int, build: int) -> bytes:
        buf = bytearray()
        buf += struct.pack(">i", 2) 
        buf += struct.pack(">i", 56)
        buf += struct.pack(">i", major)
        buf += struct.pack(">i", revision)
        buf += struct.pack(">i", build)
        AssetsDownloader._write_sc_string(buf, PATCH_NAMESPACE)
        buf += struct.pack(">i", 2)
        buf += struct.pack(">i", 2)
        return bytes(buf)

    @staticmethod
    def _build_supercell_message(message_id: int, body: bytes, version: int) -> bytes:
        header = struct.pack(">H", message_id)
        header += struct.pack(">I", len(body))[1:]
        header += struct.pack(">H", version)
        return header + body


    @staticmethod
    def _read_exactly(sock: socket.socket, size: int) -> bytes:
        buf = b""
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                raise EOFError("Unexpected EOF")
            buf += chunk
        return buf

    @classmethod
    def _read_login_failed_body(cls, sock: socket.socket) -> bytes:
        while True:
            header = cls._read_exactly(sock, 7)
            message_id = struct.unpack(">H", header[0:2])[0]
            body_length = int.from_bytes(header[2:5], "big")
            version = struct.unpack(">H", header[5:7])[0]
            logger.debug("recv msg={} len={} ver={}", message_id, body_length, version)
            body = cls._read_exactly(sock, body_length)
            if message_id == LOGIN_FAILED_ID:
                return body


    class _ByteReader:
        def __init__(self, data: bytes):
            self.data = data
            self.offset = 0

        def read_int32(self) -> Optional[int]:
            if self.offset + 4 > len(self.data):
                return None
            value = struct.unpack(">i", self.data[self.offset:self.offset + 4])[0]
            self.offset += 4
            return value

        def read_sc_string(self) -> Optional[str]:
            if self.offset + 4 > len(self.data):
                return None
            length = struct.unpack(">i", self.data[self.offset:self.offset + 4])[0]
            self.offset += 4
            if length < 0:
                return None
            if self.offset + length > len(self.data):
                return None
            value = self.data[self.offset:self.offset + length].decode("utf-8", errors="replace")
            self.offset += length
            return value

        def read_boolean(self) -> Optional[bool]:
            if self.offset + 1 > len(self.data):
                return None
            value = self.data[self.offset] != 0
            self.offset += 1
            return value

        def read_byte_string(self) -> Optional[bytes]:
            if self.offset + 4 > len(self.data):
                return None
            length = struct.unpack(">i", self.data[self.offset:self.offset + 4])[0]
            self.offset += 4
            if length < 0:
                return None
            if self.offset + length > len(self.data):
                return None
            value = self.data[self.offset:self.offset + length]
            self.offset += length
            return value

        def current_offset(self) -> int:
            return self.offset

    @classmethod
    def _parse_login_failed_prefix(cls, body: bytes) -> Optional[dict]:
        reader = cls._ByteReader(body)
        reason = reader.read_int32()
        if reason is None:
            return None
        fingerprint = reader.read_sc_string()
        unknown_string = reader.read_sc_string()
        content_download_url = reader.read_sc_string()
        update_url = reader.read_sc_string()
        reason_text = reader.read_sc_string()
        maintenance_wait_secs = reader.read_int32()
        if maintenance_wait_secs is None:
            return None
        suffix = body[reader.current_offset():]
        return {
            "reason": reason,
            "fingerprint": fingerprint,
            "unknown_string": unknown_string,
            "content_download_url": content_download_url,
            "update_url": update_url,
            "reason_text": reason_text,
            "maintenance_wait_secs": maintenance_wait_secs,
            "suffix": suffix,
        }

    @classmethod
    def _parse_login_failed_tail(cls, suffix: bytes) -> Optional[dict]:
        reader = cls._ByteReader(suffix)
        unknown_boolean = reader.read_boolean()
        if unknown_boolean is None:
            return None
        compressed_fingerprint = reader.read_byte_string()
        count = reader.read_int32()
        if count is None or count < 0 or count > 128:
            return None
        urls = []
        for _ in range(count):
            url = reader.read_sc_string()
            if url is None:
                return None
            urls.append(url)
        return {
            "unknown_boolean": unknown_boolean,
            "compressed_fingerprint": compressed_fingerprint,
            "content_download_urls": urls,
            "raw_suffix": suffix[reader.current_offset():],
        }

    @staticmethod
    def _inflate_fingerprint(data: bytes) -> Optional[str]:
        candidates = []
        if len(data) > 4:
            candidates.append(data[4:])  

        for candidate in candidates:
            for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16):
                try:
                    return zlib.decompress(candidate, wbits).decode("utf-8")
                except Exception:
                    continue
        return None

    @classmethod
    def _extract_fingerprint_json(cls, parsed: dict, tail: Optional[dict]) -> Optional[str]:
        plain = (parsed.get("fingerprint") or "").strip()
        if plain.startswith("{"):
            return plain
        if tail and tail.get("compressed_fingerprint"):
            return cls._inflate_fingerprint(tail["compressed_fingerprint"])
        return None

    def _get_fingerprint(self, ip: str, port: int = 9339,
                      major: int = 0, revision: int = 0, build: int = 0) -> Optional[str]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect((ip, port))
            client.settimeout(15)

            body = self._build_client_hello_body(major, revision, build)
            message = self._build_supercell_message(CLIENT_HELLO_ID, body, HELLO_VERSION)
            logger.debug("header: {}", message[:7].hex())
            logger.debug("full message ({} bytes): {}", len(message), message.hex())
            client.sendall(message)

            login_failed_body = self._read_login_failed_body(client)

            parsed = self._parse_login_failed_prefix(login_failed_body)
            if parsed is None:
                logger.error("Failed to parse LOGIN_FAILED prefix from {}", ip)
                return None

            logger.debug(
                "parsed prefix: reason={} fingerprint={!r} unknown={!r} contentUrl={!r} "
                "updateUrl={!r} reasonText={!r} maintenance={} suffixLen={}",
                parsed["reason"], parsed["fingerprint"], parsed["unknown_string"],
                parsed["content_download_url"], parsed["update_url"], parsed["reason_text"],
                parsed["maintenance_wait_secs"], len(parsed["suffix"])
            )
            tail = self._parse_login_failed_tail(parsed["suffix"])
            if tail is None:
                logger.error("Failed to parse LOGIN_FAILED tail (see suffix hex above)")
            else:
                logger.debug(
                    "parsed tail: unknownBool={} compressedLen={} urls={} rawSuffixLen={}",
                    tail["unknown_boolean"],
                    len(tail["compressed_fingerprint"]) if tail["compressed_fingerprint"] else -1,
                    tail["content_download_urls"],
                    len(tail["raw_suffix"])
                )

            fingerprint_json = self._extract_fingerprint_json(parsed, tail)
            if fingerprint_json is None:
                logger.error(
                    "Fingerprint not found in LOGIN_FAILED from {} (reason={}, suffixLen={})",
                    ip, parsed["reason"], len(parsed["suffix"])
                )
                return None

            try:
                root_sha = json.loads(fingerprint_json).get("sha")
            except Exception:
                root_sha = None

            logger.info("Fetched fingerprint from {} rootSha={}", ip, root_sha)
            return json.loads(fingerprint_json)
