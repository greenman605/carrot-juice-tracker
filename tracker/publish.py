"""Sync the results with GitHub: pull before a check, commit and push after it.

Walmart and IGA block cloud servers (including GitHub Actions), so checks run on a home
PC and the results are pushed to GitHub, where Pages serves the tracker page.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _git_exe() -> str:
    return shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


def git(*args: str, check: bool = True) -> str:
    kwargs = {}
    if os.name == "nt":
        # Give git (and the credential helper it starts) a hidden console, so a
        # scheduled run never flashes a window.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs = {"startupinfo": si, "creationflags": subprocess.CREATE_NEW_CONSOLE}
    r = subprocess.run([_git_exe(), *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **kwargs)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def pull(log) -> None:
    try:
        git("pull", "--rebase", "--autostash", "-q")
    except RuntimeError as e:
        git("rebase", "--abort", check=False)
        log(f"publish: could not pull from GitHub, continuing with local data ({e})")


DATA_PATHS = ("docs/data", "tracker/walmart_ops.json")


def push(log, ts: str) -> None:
    git("add", *DATA_PATHS)
    if git("diff", "--cached", "--name-only", "--", *DATA_PATHS):
        git("commit", "-q", "-m", f"Stock check {ts}", "--", *DATA_PATHS)  # data files only
    try:
        git("push", "-q")
        log("publish: pushed to GitHub")
    except RuntimeError as e:
        log(f"publish: push failed, will retry on the next run ({e})")
