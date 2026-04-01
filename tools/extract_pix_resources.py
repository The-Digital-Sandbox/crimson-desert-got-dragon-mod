#!/usr/bin/env python3
"""Extract specific PIX capture resources from resources.bin.

This replays the `g_resourceReader->Read(...)` order defined by the generated
PIX C++ project so we can dump selected live buffers directly from the capture.

Current target resources:
- 242   : stride-156 render-parameter buffer
- 7879  : stride-28 runtime instance/draw-record buffer
- 7968  : raw UAV / indirect staging buffer
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
GPU_ANALYSIS = ROOT / "gpu-analysis"
OUTPUT_DIR = ROOT / "output" / "pix_resources"
DEFAULT_RESOURCES_BIN = Path(r"C:\Users\waelj\Desktop\Outputs\resources.bin")

FRAME_RESOURCE_CALL_RE = re.compile(r"CreateAndInitResource_(\d+)\(\);")
RESOURCE_BLOCK_RE = re.compile(
    r"// ApiObjectId\s*=\s*(\d+)\s*\nvoid CreateAndInitResource_\1\(\)\s*\{\n(?P<body>.*?)\n\}",
    re.S,
)
FUNCTION_DEF_RE = re.compile(r"(?m)^void\s+([A-Za-z0-9_]+)\s*\(\)\s*\{")
READ_SIZE_RE = re.compile(r"g_resourceReader->Read\(\w+,\s*(\d+)\);")
RESOURCE_DESC_SIZE_RE = re.compile(
    r"D3D12_RESOURCE_DESC resourceDesc = \{ D3D12_RESOURCE_DIMENSION_BUFFER,\s*65536,\s*(\d+),\s*1,\s*1,\s*1,"
)
READER_CHUNK_RE = re.compile(r"g_resourceReader->Read\(\w+,\s*(\d+)\);")

COMPRESS_ALGORITHM_XPRESS = 3
ERROR_INSUFFICIENT_BUFFER = 122


@dataclass
class ResourceReadInfo:
    resource_id: int
    compressed_size: int
    decompressed_size: int
    source_file: str


def parse_resource_read_infos() -> dict[int, ResourceReadInfo]:
    result: dict[int, ResourceReadInfo] = {}
    for path in sorted(GPU_ANALYSIS.glob("CreateAndInitResources_*.cpp")):
        text = path.read_text(encoding="utf-8")
        for match in RESOURCE_BLOCK_RE.finditer(text):
            resource_id = int(match.group(1))
            body = match.group("body")
            chunk_match = READER_CHUNK_RE.search(body)
            size_match = RESOURCE_DESC_SIZE_RE.search(body)
            if not chunk_match or not size_match:
                continue
            result[resource_id] = ResourceReadInfo(
                resource_id=resource_id,
                compressed_size=int(chunk_match.group(1)),
                decompressed_size=int(size_match.group(1)),
                source_file=path.name,
            )
    return result


def parse_call_order() -> list[int]:
    frame_resources = GPU_ANALYSIS / "FrameResources_000.cpp"
    text = frame_resources.read_text(encoding="utf-8")
    return [int(match.group(1)) for match in FRAME_RESOURCE_CALL_RE.finditer(text)]


def extract_function_body(text: str, start_index: int) -> str:
    brace_index = text.find("{", start_index)
    if brace_index < 0:
        raise ValueError("function body start not found")
    depth = 0
    for index in range(brace_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1 : index]
    raise ValueError("function body end not found")


def parse_read_sizes_by_function() -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for path in sorted(GPU_ANALYSIS.glob("*.cpp")):
        text = path.read_text(encoding="utf-8")
        for match in FUNCTION_DEF_RE.finditer(text):
            function_name = match.group(1)
            body = extract_function_body(text, match.start())
            sizes = [int(read_match.group(1)) for read_match in READ_SIZE_RE.finditer(body)]
            if sizes:
                result[function_name] = sizes
    return result


def parse_create_app_resources_sequence() -> list[str]:
    frame_resources = GPU_ANALYSIS / "FrameResources_000.cpp"
    text = frame_resources.read_text(encoding="utf-8")
    start = text.find("void CreateAppResources_000()")
    if start < 0:
        raise ValueError("CreateAppResources_000 not found")
    body = extract_function_body(text, start)
    sequence: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        call_match = re.match(r"([A-Za-z0-9_]+)\(\);", stripped)
        if call_match:
            sequence.append(call_match.group(1))
    return sequence


class XpressDecompressor:
    def __init__(self) -> None:
        self._cabinet = ctypes.WinDLL("cabinet.dll", use_last_error=True)
        self._handle = ctypes.c_void_p()

        create_decompressor = self._cabinet.CreateDecompressor
        create_decompressor.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        create_decompressor.restype = ctypes.c_bool

        if not create_decompressor(COMPRESS_ALGORITHM_XPRESS, None, ctypes.byref(self._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

        self._decompress = self._cabinet.Decompress
        self._decompress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._decompress.restype = ctypes.c_bool

        self._close = self._cabinet.CloseDecompressor
        self._close.argtypes = [ctypes.c_void_p]
        self._close.restype = ctypes.c_bool

    def decompress(self, compressed_data: bytes, expected_size: int | None = None) -> bytes:
        input_buffer = ctypes.create_string_buffer(compressed_data)
        output_size = ctypes.c_size_t()

        ok = self._decompress(
            self._handle,
            input_buffer,
            len(compressed_data),
            None,
            0,
            ctypes.byref(output_size),
        )
        if ok:
            raise RuntimeError("unexpected success querying decompressed size")

        error_code = ctypes.get_last_error()
        if error_code != ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(error_code)

        if expected_size is not None and output_size.value != expected_size:
            raise ValueError(f"unexpected decompressed size {output_size.value}, expected {expected_size}")

        output_buffer = ctypes.create_string_buffer(output_size.value)
        actual_size = ctypes.c_size_t()
        ok = self._decompress(
            self._handle,
            input_buffer,
            len(compressed_data),
            output_buffer,
            output_size.value,
            ctypes.byref(actual_size),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

        return output_buffer.raw[: actual_size.value]

    def close(self) -> None:
        if self._handle:
            self._close(self._handle)
            self._handle = ctypes.c_void_p()

    def __enter__(self) -> "XpressDecompressor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def extract_resources(resources_bin: Path, target_ids: Iterable[int]) -> dict[int, dict]:
    target_set = set(target_ids)
    infos = parse_resource_read_infos()
    call_order = parse_create_app_resources_sequence()
    function_reads = parse_read_sizes_by_function()

    missing = [resource_id for resource_id in target_set if resource_id not in infos]
    if missing:
        raise ValueError(f"missing resource metadata for ids: {missing}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[int, dict] = {}
    current_offset = 0

    with resources_bin.open("rb") as handle, XpressDecompressor() as decompressor:
        for function_name in call_order:
            read_sizes = function_reads.get(function_name)
            if not read_sizes:
                continue
            target_match = re.fullmatch(r"CreateAndInitResource_(\d+)", function_name)
            target_resource_id = int(target_match.group(1)) if target_match else None

            for read_index, compressed_size in enumerate(read_sizes):
                compressed_offset = current_offset
                compressed_data = handle.read(compressed_size)
                if len(compressed_data) != compressed_size:
                    raise EOFError(f"unexpected EOF reading compressed chunk for {function_name}")
                current_offset += compressed_size

                if target_resource_id is None or target_resource_id not in target_set:
                    continue
                if read_index != 0:
                    continue

                info = infos[target_resource_id]
                decompressed = decompressor.decompress(compressed_data, expected_size=info.decompressed_size)
                out_path = OUTPUT_DIR / f"resource_{target_resource_id}.bin"
                out_path.write_bytes(decompressed)

                manifest[target_resource_id] = {
                    "resource_id": target_resource_id,
                    "source_file": info.source_file,
                    "function_name": function_name,
                    "compressed_offset": compressed_offset,
                    "compressed_size": compressed_size,
                    "decompressed_size": len(decompressed),
                    "output_path": str(out_path),
                }

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract selected resources from PIX resources.bin")
    parser.add_argument(
        "--resources-bin",
        type=Path,
        default=DEFAULT_RESOURCES_BIN,
        help="Path to PIX resources.bin",
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        type=int,
        default=[242, 7879, 7968],
        help="Resource ids to extract",
    )
    args = parser.parse_args()

    manifest = extract_resources(args.resources_bin, args.ids)
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")

    for resource_id in args.ids:
        if resource_id in manifest:
            info = manifest[resource_id]
            print(
                f"resource {resource_id}: offset={info['compressed_offset']} "
                f"compressed={info['compressed_size']} decompressed={info['decompressed_size']} "
                f"-> {info['output_path']}"
            )
        else:
            print(f"resource {resource_id}: not found in call order")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
