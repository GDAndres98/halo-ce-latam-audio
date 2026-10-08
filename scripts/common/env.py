"""Minimal .env reader (stdlib only). Values are never logged in full by callers."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env(path=None):
    path = Path(path) if path else REPO_ROOT / ".env"
    env = {}
    problems = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            problems.append(f"{path.name}:{lineno}: no '=' in line")
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"')
    return env, problems


def require_path(env, key, kind="file"):
    """Return Path for env[key], raising a clear error if missing or wrong kind."""
    if key not in env:
        raise SystemExit(f"{key} is not set in .env")
    p = Path(env[key])
    ok = p.is_file() if kind == "file" else p.is_dir()
    if not ok:
        raise SystemExit(f"{key} does not point to an existing {kind}: {p}")
    return p
