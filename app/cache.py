"""
Caché HTTP en disco. Todo lo que viene de una API externa pasa por aquí.

- Clave = sha1(método + URL completa + cuerpo). Fichero: data/cache/<source>/<clave>.bin
  más <clave>.json con la URL, la fecha de descarga y el Content-Type.
- Solo se guarda lo que la función `validate` da por bueno: un 503.2 dentro de HTTP 200
  NUNCA entra en caché.
- Si está en caché no se toca la red: la demo funciona sin conexión una vez precargada.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

from .config import CACHE, USER_AGENT

_client: httpx.Client | None = None
_client_lock = threading.Lock()


def client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                                   limits=httpx.Limits(max_connections=16))
        return _client


@dataclass
class Cached:
    content: bytes
    url: str
    fetched_at: str
    content_type: str
    from_cache: bool

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class FetchError(Exception):
    """Fallo de red o respuesta no válida (no se cachea)."""


def full_url(url: str, params=None) -> str:
    return str(httpx.Request("GET", url, params=params).url)


def _key(method: str, url: str, body: bytes | None) -> str:
    h = hashlib.sha1(f"{method} {url}".encode())
    if body:
        h.update(b"\n" + body)
    return h.hexdigest()


def cache_dir(source: str) -> Path:
    return CACHE / source


def lookup(source: str, method: str, url: str, body: bytes | None = None) -> Cached | None:
    d = cache_dir(source)
    k = _key(method, url, body)
    bin_path, meta_path = d / f"{k}.bin", d / f"{k}.json"
    if bin_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return Cached(bin_path.read_bytes(), meta["url"], meta["fetched_at"],
                      meta.get("content_type", ""), True)
    return None


def store(source: str, method: str, url: str, body: bytes | None, content: bytes,
          content_type: str) -> Cached:
    d = cache_dir(source)
    d.mkdir(parents=True, exist_ok=True)
    k = _key(method, url, body)
    fetched = datetime.now().isoformat(timespec="seconds")
    (d / f"{k}.bin").write_bytes(content)
    (d / f"{k}.json").write_text(json.dumps(
        {"url": url, "method": method, "body": body.decode("utf-8", "replace")[:2000] if body else None,
         "fetched_at": fetched, "content_type": content_type}, ensure_ascii=False), encoding="utf-8")
    return Cached(content, url, fetched, content_type, False)


def fetch(source: str, url: str, params=None, *, method: str = "GET", data: dict | None = None,
          timeout: float = 60, validate: Callable[[httpx.Response], str | None] | None = None) -> Cached:
    """GET/POST cacheado. `validate(resp)` devuelve None si es válida o un texto de error.

    Lanza FetchError si falla (red, HTTP != 200 o validate); nunca cachea un fallo.
    """
    url_full = full_url(url, params)
    body = httpx.QueryParams(data).__str__().encode() if data else None
    hit = lookup(source, method, url_full, body)
    if hit:
        return hit
    try:
        if method == "POST":
            r = client().post(url_full, data=data, timeout=timeout)
        else:
            r = client().get(url_full, timeout=timeout)
    except httpx.HTTPError as exc:
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}: {r.text[:300]}")
    if validate:
        err = validate(r)
        if err:
            raise FetchError(err)
    return store(source, method, url_full, body, r.content, r.headers.get("Content-Type", ""))


def clear(source: str | None = None) -> list[str]:
    """Vacía la caché de una fuente (o de todas). Devuelve las fuentes vaciadas."""
    if not CACHE.exists():
        return []
    targets = [cache_dir(source)] if source else [p for p in CACHE.iterdir() if p.is_dir()]
    done = []
    for d in targets:
        if d.exists():
            shutil.rmtree(d)
            done.append(d.name)
    return done
