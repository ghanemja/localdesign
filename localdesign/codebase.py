"""Code context: a folder of the user's existing source, stored per project and referenced from prompts.

The browser uploads text files (already filtered); we re-filter, store them in ~/.localdesign/code/<project>.json,
and for each model call build a context block from the files the prompt mentions (``@src/pages/Settings.tsx``,
``@Button``, ``@src/components/``) plus the files the user pinned, within a character budget. Nothing else is sent.
"""
from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from pathlib import PurePosixPath

from . import config, prompts

MAX_FILE = 256_000        # chars per file
MAX_TOTAL = 8_000_000     # chars per project
MAX_FILES = 5000

SKIP_DIRS = {
    "node_modules", ".git", ".hg", ".svn", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit", ".output", ".vercel",
    "coverage", "__pycache__", ".venv", "venv", "site-packages", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "vendor", "target", ".idea", ".vscode", ".turbo", ".cache", ".parcel-cache", "Pods", "DerivedData", ".gradle",
    "obj", ".expo", ".angular", "storybook-static", "bower_components", ".yarn", ".pnpm-store", ".terraform",
}
TEXT_EXT = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte", ".astro", ".html", ".htm", ".css", ".scss",
    ".sass", ".less", ".styl", ".pcss", ".json", ".json5", ".jsonc", ".md", ".mdx", ".txt", ".yml", ".yaml", ".toml", ".ini",
    ".xml", ".svg", ".graphql", ".gql", ".prisma", ".sql", ".py", ".rb", ".go", ".rs", ".java", ".kt", ".kts", ".swift", ".dart",
    ".php", ".cs", ".cshtml", ".razor", ".fs", ".scala", ".ex", ".exs", ".erb", ".hbs", ".handlebars", ".ejs", ".pug", ".liquid",
    ".njk", ".twig", ".jinja", ".j2", ".lua", ".r", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".tf", ".proto", ".csv",
}
TEXT_NAMES = {"dockerfile", "makefile", "procfile", "gemfile", "rakefile", "justfile", ".env.example", ".env.sample", ".env.template"}
# never stored, even if the browser sends them: lockfiles (huge, useless) and files that usually hold secrets
SKIP_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "cargo.lock", "uv.lock", "composer.lock", "gemfile.lock",
    "bun.lockb", "pipfile.lock", "go.sum", ".ds_store", "secrets.yml", "secrets.yaml", "secrets.json", "credentials.json",
    "credentials.yml", "service-account.json", "id_rsa", "id_ed25519",
}
LANG = {".ts": "ts", ".tsx": "tsx", ".js": "js", ".jsx": "jsx", ".mjs": "js", ".cjs": "js", ".py": "python", ".rb": "ruby",
        ".css": "css", ".scss": "scss", ".html": "html", ".htm": "html", ".vue": "vue", ".svelte": "svelte", ".json": "json",
        ".md": "markdown", ".yml": "yaml", ".yaml": "yaml", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
        ".swift": "swift", ".dart": "dart", ".php": "php", ".cs": "csharp", ".sql": "sql", ".svg": "svg", ".xml": "xml"}


def clean_path(p) -> str | None:
    """Normalise an uploaded relative path ('./src\\a.ts' → 'src/a.ts'); None for anything absolute-ish or with '..'."""
    if not isinstance(p, str):
        return None
    p = p.replace("\\", "/").strip()
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts) or re.match(r"^[a-zA-Z]:$", parts[0]) or len(p) > 400:
        return None
    return "/".join(parts)


def keep(path: str) -> bool:
    """Is this a source/text file worth keeping? (Skips vendored dirs, binaries, lockfiles, minified bundles, secrets.)"""
    parts = path.split("/")
    if any(d in SKIP_DIRS for d in parts[:-1]):
        return False
    name = parts[-1].lower()
    if name in SKIP_NAMES or name.endswith((".min.js", ".min.css", ".map", ".pem", ".key", ".p12", ".pfx")):
        return False
    if name == ".env" or (name.startswith(".env.") and name not in TEXT_NAMES):
        return False
    return name in TEXT_NAMES or PurePosixPath(name).suffix in TEXT_EXT


def store_path(pid: str):
    return config.CODE_DIR / f"{pid}.json"


def load(pid: str) -> dict | None:
    try:
        d = json.loads(store_path(pid).read_text())
        return d if isinstance(d.get("files"), dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def delete(pid: str) -> bool:
    try:
        store_path(pid).unlink()
        return True
    except FileNotFoundError:
        return False


def save(pid: str, name: str, files: list, add: bool = False) -> dict:
    """Store uploaded files ({path, content}); add=True merges into what is there. Returns the index."""
    old = load(pid) if add else None
    store = {"name": (old or {}).get("name") or str(name or "code")[:80], "files": dict((old or {}).get("files") or {}), "updated": time.time()}
    skipped = 0
    total = sum(len(v) for v in store["files"].values())
    for f in files if isinstance(files, list) else []:
        path = clean_path(f.get("path")) if isinstance(f, dict) else None
        content = f.get("content") if isinstance(f, dict) else None
        if not path or not isinstance(content, str) or not keep(path) or "\x00" in content or len(content) > MAX_FILE:
            skipped += 1
            continue
        if path not in store["files"] and len(store["files"]) >= MAX_FILES:
            skipped += 1
            continue
        total += len(content) - len(store["files"].get(path, ""))
        if total > MAX_TOTAL:
            total -= len(content) - len(store["files"].get(path, ""))
            skipped += 1
            continue
        store["files"][path] = content
    if not store["files"]:
        raise ValueError("no usable source files (text files only; node_modules, build output, binaries, lockfiles and .env are skipped)")
    config.CODE_DIR.mkdir(parents=True, exist_ok=True)
    store_path(pid).write_text(json.dumps(store))
    return {**index(store), "skipped": skipped, "style": style_files(store)}


def index(store: dict) -> dict:
    files = store["files"]
    return {"name": store.get("name") or "code", "files": [{"path": p, "size": len(c)} for p, c in sorted(files.items())],
            "bytes": sum(len(c) for c in files.values())}


_STYLE = [
    (0, re.compile(r"(^|/)tailwind\.config\.(js|ts|cjs|mjs)$")),
    (1, re.compile(r"(^|/)(theme|tokens|design-tokens|_?variables|colors)\.(ts|js|json|css|scss)$", re.I)),
    (2, re.compile(r"(^|/)(globals?|index|app|main|styles?|base)\.(css|scss)$", re.I)),
]


def style_files(store: dict, limit: int = 3) -> list[str]:
    """Files that define the look (Tailwind config, theme/tokens, a global stylesheet with variables): auto-pinned on attach."""
    found = []
    for path, content in store["files"].items():
        if len(content) > 16_000:
            continue
        for rank, rx in _STYLE:
            if rx.search(path):
                if rank == 2 and not re.search(r"--[\w-]+\s*:|@tailwind|@theme|@import\s+[\"']tailwindcss", content):
                    break   # a stylesheet without variables/tailwind says little about the design system
                found.append((rank, path.count("/"), path))
                break
    return [p for _, _, p in sorted(found)[:limit]]


# ------------------------------------------------------------------ mentions + prompt block
MENTION = re.compile(r"(?<![\w@/])@([A-Za-z0-9_.\-/\[\]()+~$]+)")


def _resolve(token: str, paths: list[str], pathset: set[str]) -> list[str]:
    t = token.rstrip(".,;:!?)'\"").lstrip("/")
    if t.startswith("./"):
        t = t[2:]
    if not t:
        return []
    if t in pathset:
        return [t]
    d = t.rstrip("/") + "/"
    under = [p for p in paths if p.startswith(d)]
    if under:
        return under
    tl = t.lower()
    suf = [p for p in paths if p.lower() == tl or p.lower().endswith("/" + tl)]
    if suf:
        return suf[:3]
    return [p for p in paths if PurePosixPath(p).stem.lower() == tl][:3]   # @Button → src/components/Button.tsx


def mentions(text: str, paths: list[str]) -> tuple[list[str], list[str]]:
    """@tokens in text → (matched file paths in order, unresolved tokens)."""
    pathset = set(paths)
    out: "OrderedDict[str, None]" = OrderedDict()
    unresolved = []
    for m in MENTION.finditer(text or ""):
        hits = _resolve(m.group(1), paths, pathset)
        if hits:
            out.update((h, None) for h in hits)
        else:
            unresolved.append(m.group(1).rstrip(".,;:!?)'\""))
    return list(out), list(OrderedDict.fromkeys(u for u in unresolved if u))


def tree_text(paths: list[str], limit: int) -> str:
    """Compact listing grouped by folder ('src/components/: Button.tsx, Card.tsx'), capped at `limit` chars."""
    groups: "OrderedDict[str, list[str]]" = OrderedDict()
    for p in sorted(paths, key=lambda p: (p.count("/"), p)):
        d, _, f = p.rpartition("/")
        groups.setdefault(d, []).append(f)
    lines, used = [], 0
    for i, (d, names) in enumerate(groups.items()):
        line = f"{d + '/' if d else '(root)'}: " + ", ".join(names)
        if len(line) > 300:
            line = line[:290].rsplit(", ", 1)[0] + f", … (+{len(names)} total)"
        if used + len(line) + 1 > limit:
            lines.append(f"… {len(groups) - i} more folders")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def context(store: dict, text: str, pins: list[str], budget: int) -> tuple[str, dict]:
    """The prompt block for one model call + what went into it (for the UI and the audit log)."""
    files = store["files"]
    paths = sorted(files)
    mentioned, unresolved = mentions(text, paths)
    chosen = list(OrderedDict.fromkeys([*mentioned, *(p for p in pins if p in files)]))
    head = prompts.CODE_CONTEXT.format(name=store.get("name") or "code", count=len(paths))
    tree = tree_text(paths, max(300, min(4000, budget // 6)))
    parts = [head, "Files in the codebase:\n" + tree]
    used = len(head) + len(tree)
    included, omitted = [], []
    for p in chosen:
        body = files[p]
        room = budget - used - len(p) - 40
        if room < 400:
            omitted.append(p)
            continue
        cut = len(body) > room
        if cut:
            body = body[:room].rsplit("\n", 1)[0] + "\n… [truncated]"
        parts.append(f"File {p}:\n```{LANG.get(PurePosixPath(p).suffix.lower(), '')}\n{body}\n```")
        used += len(p) + len(body) + 40
        included.append({"path": p, "chars": len(body), "truncated": cut, "pinned": p not in mentioned})
    block = "\n\n".join(parts) + "\n\n---\n\n"
    return block, {"name": store.get("name") or "code", "files": included, "omitted": omitted, "unresolved": unresolved, "chars": len(block), "budget": budget}
