"""Public-domain imagery: search official open-access museum APIs, import a chosen image as a project asset.

Sources (no key, CC0 / public domain, official APIs):
  - Art Institute of Chicago  https://api.artic.edu/docs/   (public-domain works; images via IIIF)
  - Cleveland Museum of Art   https://openaccess-api.clevelandart.org/  (CC0)
Any other public-domain image (e.g. one you picked on pdimagearchive.org) can be imported by its URL.
Only the image file goes into the project; nothing is sent to a model except its title/credit line as text.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

UA = {"User-Agent": f"localdesign/{__version__} (local design tool)", "AIC-User-Agent": f"localdesign/{__version__} (local design tool)"}
SOURCES = {"aic": "Art Institute of Chicago", "cma": "Cleveland Museum of Art"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE = 12 * 1024 * 1024


def _get_json(url: str, timeout: float = 15) -> dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return json.loads(r.read(4_000_000))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ValueError(f"search unavailable ({getattr(e, 'reason', e)}) — offline? Import images you downloaded under My assets instead") from None


def _aic(q: str, page: int, limit: int) -> tuple[int, list]:
    qs = urllib.parse.urlencode({"q": q, "query[term][is_public_domain]": "true", "limit": limit, "page": page + 1,
                                 "fields": "id,title,image_id,artist_title,date_display,thumbnail"})
    d = _get_json(f"https://api.artic.edu/api/v1/artworks/search?{qs}")
    base = (d.get("config") or {}).get("iiif_url") or "https://www.artic.edu/iiif/2"
    out = []
    for it in d.get("data") or []:
        if not it.get("image_id"):
            continue
        th = it.get("thumbnail") or {}
        out.append({"id": f"aic-{it['id']}", "source": "aic", "title": it.get("title") or "Untitled", "artist": it.get("artist_title") or "",
                    "date": it.get("date_display") or "", "thumb": f"{base}/{it['image_id']}/full/400,/0/default.jpg",
                    "full": f"{base}/{it['image_id']}/full/1686,/0/default.jpg", "page": f"https://www.artic.edu/artworks/{it['id']}",
                    "w": th.get("width"), "h": th.get("height"), "license": "Public domain (CC0)"})
    return int((d.get("pagination") or {}).get("total") or 0), out


def _cma(q: str, page: int, limit: int) -> tuple[int, list]:
    qs = urllib.parse.urlencode({"q": q, "cc0": 1, "has_image": 1, "limit": limit, "skip": page * limit})
    d = _get_json(f"https://openaccess-api.clevelandart.org/api/artworks/?{qs}")
    out = []
    for it in d.get("data") or []:
        web = ((it.get("images") or {}).get("web") or {})
        if not web.get("url"):
            continue
        creators = it.get("creators") or []
        out.append({"id": f"cma-{it['id']}", "source": "cma", "title": it.get("title") or "Untitled", "artist": (creators[0].get("description") if creators else "") or "",
                    "date": it.get("creation_date") or "", "thumb": web["url"], "full": ((it.get("images") or {}).get("print") or web).get("url") or web["url"],
                    "page": it.get("url") or "", "w": web.get("width"), "h": web.get("height"), "license": "CC0"})
    return int((d.get("info") or {}).get("total") or 0), out


def search(q: str, source: str = "all", page: int = 0, limit: int = 24) -> dict:
    q = (q or "").strip()[:120] or "botanical illustration"
    limit = max(4, min(int(limit or 24), 48))
    fns = {"aic": _aic, "cma": _cma}
    use = [source] if source in fns else list(fns)
    per = limit if len(use) == 1 else limit // 2
    total, items, errors = 0, [], []
    results = []
    for s in use:
        try:
            n, its = fns[s](q, page, per)
            total += n
            results.append(its)
        except ValueError as e:
            errors.append(f"{SOURCES[s]}: {e}")
    for i in range(max((len(r) for r in results), default=0)):      # interleave sources
        items += [r[i] for r in results if i < len(r)]
    if not items and errors:
        raise ValueError("; ".join(errors))
    return {"total": total, "items": items, "page": page, "errors": errors}


THUMB_HOSTS = {"www.artic.edu", "openaccess-cdn.clevelandart.org"}
_THUMBS: "dict[str, tuple[bytes, str]]" = {}


def thumb(url: str) -> tuple[bytes, str]:
    """Search-result thumbnails, fetched by the server (museum image hosts only; small in-memory cache)."""
    from urllib.parse import urlparse
    if urlparse(url).hostname not in THUMB_HOSTS or not url.startswith("https://"):
        raise ValueError("not a museum thumbnail")
    if url not in _THUMBS:
        if len(_THUMBS) > 400:
            _THUMBS.pop(next(iter(_THUMBS)))
        _THUMBS[url] = download(url, timeout=15)
    return _THUMBS[url]


def download(url: str, timeout: float = 25) -> tuple[bytes, str]:
    """Fetch an image (http/https, ≤ 12 MB, jpeg/png/gif/webp)."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("only http(s) image URLs")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = r.read(MAX_IMAGE + 1)
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code} fetching the image") from None
    except (urllib.error.URLError, OSError) as e:
        raise ValueError(f"cannot fetch the image ({getattr(e, 'reason', e)})") from None
    if len(data) > MAX_IMAGE:
        raise ValueError("image is larger than 12 MB")
    if ctype not in IMAGE_TYPES:
        sniff = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"GIF8": "image/gif", b"RIFF": "image/webp"}
        ctype = next((t for sig, t in sniff.items() if data.startswith(sig)), "")
        if not ctype:
            raise ValueError("that URL is not a JPEG/PNG/GIF/WebP image (copy the image's own address, not the page's)")
    return data, ctype
