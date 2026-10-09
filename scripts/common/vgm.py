"""Thin wrappers around the approved vgmstream-cli (r2117) for offline checks. Read-only on inputs."""
import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")


def decode_pcm(exe, path, subsong):
    """Decoded WAV bytes of one subsong via stdout (-p), or None on failure. Nothing is written."""
    res = subprocess.run([str(exe), "-p", "-s", str(subsong), str(path)], capture_output=True)
    return res.stdout if res.returncode == 0 and len(res.stdout) > 44 else None


def decode_hash(exe, path, subsong):
    pcm = decode_pcm(exe, path, subsong)
    return hashlib.sha256(pcm).hexdigest() if pcm is not None else None


def decode_all(exe, path, count, workers=8):
    """SHA-256 of every subsong's decoded WAV (1..count), decoded in parallel."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda k: decode_hash(exe, path, k), range(1, count + 1)))


def meta(exe, path, subsong):
    """`vgmstream-cli -m` lines, minus the ones naming the file path."""
    res = subprocess.run([str(exe), "-m", "-s", str(subsong), str(path)], capture_output=True, text=True)
    return [ln for ln in res.stdout.splitlines() if str(path) not in ln and "metadata for" not in ln.lower()]


def meta_value(lines, key):
    for ln in lines:
        if ln.lower().startswith(key.lower() + ":"):
            return ln.split(":", 1)[1].strip()
    return None
