#!/usr/bin/env python3
"""Windows/macOS/Linux helper to pull WeChat data from a rooted Android phone.

This is a cross-platform replacement for android-interact.sh.  It avoids local
bash/coreutils by creating tar archives on the rooted Android device, pulling
the archive with adb, and extracting it with Python's tarfile module.

Examples:
    python android_interact.py db --out .
    python android_interact.py res --out resource
    python android_interact.py all --db-out . --res-out resource
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Iterable, Sequence

DEFAULT_RES_DIR = "/data/data/com.tencent.mm/MicroMsg"
OLD_RES_DIR = "/mnt/sdcard/tencent/MicroMsg"
DEFAULT_RESOURCE_SUBDIRS = ("avatar", "image2", "voice2", "emoji", "video", "sfs")
DEFAULT_DB_ENTRIES = ("EnMicroMsg.db", "sfs/avatar.index")
USER_DIR_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def adb_command(adb: str, device: str | None, args: Iterable[str]) -> list[str]:
    cmd = [adb]
    if device:
        cmd += ["-s", device]
    cmd += list(args)
    return cmd


def run(cmd: Sequence[str], *, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
    )
    if check and proc.returncode != 0:
        output = proc.stdout if text else (proc.stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(map(str, cmd))}\n{output}")
    return proc


def run_adb(adb: str, device: str | None, *args: str, check: bool = True) -> str:
    proc = run(adb_command(adb, device, args), check=check)
    return proc.stdout or ""


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required executable not found in PATH: {name}")


def check_adb(adb: str, device: str | None) -> None:
    print("[1/6] Checking adb device...")
    print(run_adb(adb, device, "devices").rstrip())
    print("[2/6] Checking root...")
    out = run_adb(adb, device, "shell", "su", "-c", "id")
    print(out.rstrip())
    if "uid=0" not in out:
        raise RuntimeError("adb works, but root via `su -c id` did not return uid=0")


def list_users(adb: str, device: str | None, res_dir: str) -> list[str]:
    # Keep the device-side shell simple for compatibility with toybox/busybox.
    out = run_adb(adb, device, "shell", "su", "-c", f"ls -1 {sh_quote(res_dir)} 2>/dev/null", check=False)
    users = [line.strip() for line in out.splitlines() if USER_DIR_RE.match(line.strip())]
    return users


def choose_user(adb: str, device: str | None, res_dir: str, requested_user: str | None) -> str:
    print("[3/6] Locating WeChat user directory...")
    if requested_user:
        if not USER_DIR_RE.match(requested_user):
            raise RuntimeError(f"--user must be a 32-character hex directory name: {requested_user}")
        print(f"Using user supplied with --user: {requested_user}")
        return requested_user

    users = list_users(adb, device, res_dir)
    if not users:
        raise RuntimeError(f"No 32-character user directory found under {res_dir}")
    chosen = users[0]
    print(f"Found {len(users)} user(s): {', '.join(users)}")
    print(f"Using: {chosen}")
    if len(users) > 1:
        print("Pass --user <32-hex-dir> to choose a different account.")
    return chosen


def make_device_archive(
    adb: str,
    device: str | None,
    *,
    user_root: str,
    entries: Sequence[str],
    archive_kind: str,
) -> str:
    remote_archive = f"/data/local/tmp/wechat-dump-{archive_kind}-{int(time.time())}-{os.getpid()}.tar"
    # Build an $entries variable on-device containing only existing files/dirs.
    add_entries = []
    for entry in entries:
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", entry):
            raise RuntimeError(f"Refusing unsafe archive entry: {entry!r}")
        q = sh_quote(entry)
        add_entries.append(f"[ -e {q} ] && entries=\"$entries {entry}\"")
    add_entries_script = "; ".join(add_entries)
    # Use busybox tar when available; fall back to Android toybox tar.
    script = (
        f"cd {sh_quote(user_root)} || exit 10; "
        "entries=; "
        f"{add_entries_script}; "
        "[ -n \"$entries\" ] || exit 44; "
        f"rm -f {sh_quote(remote_archive)}; "
        f"(busybox tar -cf {sh_quote(remote_archive)} $entries 2>/dev/null || "
        f"tar -cf {sh_quote(remote_archive)} $entries) && "
        f"chmod 666 {sh_quote(remote_archive)}"
    )
    print(f"[4/6] Creating device archive: {remote_archive}")
    out = run_adb(adb, device, "shell", "su", "-c", script, check=False)
    if out.strip():
        print(out.rstrip())
    # Verify archive exists and has non-zero size.
    stat = run_adb(
        adb,
        device,
        "shell",
        "su",
        "-c",
        f"ls -l {sh_quote(remote_archive)} 2>/dev/null",
        check=False,
    )
    if remote_archive not in stat:
        raise RuntimeError(
            "Failed to create device archive. Check that the selected user directory contains: "
            + ", ".join(entries)
        )
    return remote_archive


def safe_extract_tar(tar_path: pathlib.Path, out_dir: pathlib.Path) -> list[pathlib.Path]:
    out_dir = out_dir.resolve()
    extracted: list[pathlib.Path] = []
    with tarfile.open(tar_path, "r") as tf:
        members = [m for m in tf.getmembers() if m.name and not m.name.startswith("/")]
        for member in members:
            target = (out_dir / member.name).resolve()
            if target != out_dir and out_dir not in target.parents:
                raise RuntimeError(f"Unsafe tar path refused: {member.name}")
        tf.extractall(out_dir, members=members)
        for member in members:
            if member.isfile():
                extracted.append(out_dir / member.name)
    return extracted


def pull_and_extract(
    adb: str,
    device: str | None,
    remote_archive: str,
    out_dir: pathlib.Path,
    *,
    keep_archive: bool,
) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wechat-dump-adb-") as tmp:
        local_archive = pathlib.Path(tmp) / pathlib.PurePosixPath(remote_archive).name
        print(f"[5/6] Pulling archive to {local_archive} ...")
        print(run_adb(adb, device, "pull", remote_archive, str(local_archive)).rstrip())
        print(f"Extracting to {out_dir} ...")
        extracted = safe_extract_tar(local_archive, out_dir)
        if keep_archive:
            kept = out_dir / local_archive.name
            shutil.copy2(local_archive, kept)
            print(f"Kept archive: {kept}")
    return extracted


def cleanup_device(adb: str, device: str | None, remote_archive: str) -> None:
    print("[6/6] Cleaning device temporary archive...")
    run_adb(adb, device, "shell", "su", "-c", f"rm -f {sh_quote(remote_archive)}", check=False)


def flatten_db_outputs(out_dir: pathlib.Path) -> None:
    avatar = out_dir / "sfs" / "avatar.index"
    if avatar.is_file():
        target = out_dir / "avatar.index"
        shutil.copy2(avatar, target)
        print(f"Copied {avatar} -> {target}")


def print_tree_summary(out_dir: pathlib.Path, max_items: int = 20) -> None:
    files = [p for p in out_dir.rglob("*") if p.is_file()]
    total_size = sum(p.stat().st_size for p in files)
    print(f"Output: {out_dir}")
    print(f"Files: {len(files)}, total size: {total_size / (1024 * 1024):.1f} MiB")
    for p in sorted(files)[:max_items]:
        rel = p.relative_to(out_dir)
        print(f"  {rel}  {p.stat().st_size} bytes")
    if len(files) > max_items:
        print(f"  ... {len(files) - max_items} more file(s)")


def pull_db(args: argparse.Namespace, user: str) -> None:
    user_root = f"{args.res_dir.rstrip('/')}/{user}"
    remote = make_device_archive(
        args.adb,
        args.device,
        user_root=user_root,
        entries=DEFAULT_DB_ENTRIES,
        archive_kind="db",
    )
    try:
        out_dir = pathlib.Path(args.out or args.db_out or ".").resolve()
        pull_and_extract(args.adb, args.device, remote, out_dir, keep_archive=args.keep_archive)
        flatten_db_outputs(out_dir)
        print("Database files pulled.")
        print_tree_summary(out_dir)
    finally:
        cleanup_device(args.adb, args.device, remote)


def pull_res(args: argparse.Namespace, user: str) -> None:
    user_root = f"{args.res_dir.rstrip('/')}/{user}"
    entries = tuple(args.include or DEFAULT_RESOURCE_SUBDIRS)
    remote = make_device_archive(
        args.adb,
        args.device,
        user_root=user_root,
        entries=entries,
        archive_kind="res",
    )
    try:
        out_dir = pathlib.Path(args.out or args.res_out or "resource").resolve()
        pull_and_extract(args.adb, args.device, remote, out_dir, keep_archive=args.keep_archive)
        print("Resource files pulled.")
        print_tree_summary(out_dir)
    finally:
        cleanup_device(args.adb, args.device, remote)


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull WeChat database/resource files from a rooted Android device without bash/WSL.")
    parser.add_argument("action", choices=["db", "res", "all"], help="what to pull")
    parser.add_argument("--adb", default="adb", help="adb executable name/path")
    parser.add_argument("--device", default=None, help="optional adb serial")
    parser.add_argument("--res-dir", default=DEFAULT_RES_DIR, help=f"remote MicroMsg directory, default: {DEFAULT_RES_DIR}")
    parser.add_argument("--user", help="32-character WeChat user directory; auto-detected when omitted")
    parser.add_argument("--out", help="output dir for db/res actions")
    parser.add_argument("--db-out", default=".", help="output dir for database files when action=all")
    parser.add_argument("--res-out", default="resource", help="output dir for resources when action=all")
    parser.add_argument("--include", nargs="*", help="resource subdirectories to pull, default: avatar image2 voice2 emoji video sfs")
    parser.add_argument("--keep-archive", action="store_true", help="keep pulled tar archive in the output directory")
    parser.add_argument("--old-sdcard-layout", action="store_true", help=f"use old resource dir: {OLD_RES_DIR}")
    return parser.parse_args()


def main() -> int:
    args = get_args()
    if args.old_sdcard_layout:
        args.res_dir = OLD_RES_DIR
    require_tool(args.adb)
    check_adb(args.adb, args.device)
    user = choose_user(args.adb, args.device, args.res_dir, args.user)
    if args.action in ("db", "all"):
        pull_db(args, user)
    if args.action in ("res", "all"):
        pull_res(args, user)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
