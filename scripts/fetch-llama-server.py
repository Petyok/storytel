#!/usr/bin/env python3
"""
Download a prebuilt llama-server from the latest ggml-org/llama.cpp GitHub release.
Falls back with exit 1 if no matching asset (caller may try cmake build).
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = "ggml-org/llama.cpp"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = "storytel-install/1.0"


def machine_arch() -> str:
    m = os.uname().machine.lower()
    if m in ("x86_64", "amd64"):
        return "x64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return m


def pick_asset(assets: list[dict], arch_tag: str) -> tuple[str, str] | None:
    """Return (name, url) for a linux zip containing llama-server."""
    best: list[tuple[int, str, str]] = []
    for a in assets:
        name = a.get("name") or ""
        url = a.get("browser_download_url") or ""
        if not url or not name.lower().endswith(".zip"):
            continue
        nl = name.lower()
        if "linux" not in nl:
            continue
        score = 0
        if arch_tag == "x64" and ("x64" in nl or "x86_64" in nl):
            score = 10
        elif arch_tag == "arm64" and ("aarch64" in nl or "arm64" in nl):
            score = 10
        elif arch_tag in nl:
            score = 8
        else:
            continue
        if "ubuntu" in nl or "manylinux" in nl:
            score += 1
        best.append((score, name, url))
    if not best:
        return None
    best.sort(key=lambda x: -x[0])
    _, name, url = best[0]
    return name, url


def find_llama_server(root: Path) -> Path | None:
    for p in root.rglob("llama-server"):
        if p.is_file() and os.access(p, os.X_OK):
            return p
    for p in root.rglob("llama-server"):
        if p.is_file():
            return p
    return None


def main() -> int:
    dest = Path(os.environ.get("STORYTEL_LLAMA_DEST", "")).expanduser()
    if not dest:
        print("error: STORYTEL_LLAMA_DEST not set", file=sys.stderr)
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "llama-server"

    arch = machine_arch()
    req = urllib.request.Request(API, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    assets = data.get("assets") or []
    picked = pick_asset(assets, arch)
    if not picked:
        print(f"No linux/{arch} zip asset in latest release; try cmake build.", file=sys.stderr)
        return 1
    name, url = picked
    print(f"==> Downloading {name}")

    with tempfile.TemporaryDirectory() as td:
        zpath = Path(td) / name
        dl_req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(dl_req, timeout=600) as resp, open(zpath, "wb") as out:
            shutil.copyfileobj(resp, out)
        extract_root = Path(td) / "extract"
        extract_root.mkdir()
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(extract_root)
        binary = find_llama_server(extract_root)
        if not binary:
            print("error: llama-server not found inside zip", file=sys.stderr)
            return 1
        shutil.copy2(binary, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"    Installed: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
