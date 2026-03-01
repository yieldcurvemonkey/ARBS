import contextlib
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Generator, TypeVar

import diskcache

from Caching.CodecMapping import CodecMapping

EncodeFn = Callable[[Any], Any]
DecodeFn = Callable[[Any], Any]
T = TypeVar("T", bound="DiskCacheMixin")


class DiskCacheMixin:
    """Drop-in replacement for ZODBCacheMixin backed by diskcache.FanoutCache."""

    _CACHE_REGISTRY: Dict[str, diskcache.FanoutCache] = {}
    _REGISTRY_LOCK = threading.Lock()

    _SLUG_RX = re.compile(r"[^\w.\-]")

    CACHE_ROOT: Path | None = None

    def __init__(
        self: T,
        *,
        use_btree: bool | None = True,
        force_refresh: bool | None = False,
        **kwargs: Any,
    ) -> None:
        self._use_btree = bool(use_btree)
        self._force_refresh = bool(force_refresh)
        super().__init__(**kwargs)

        self._dc_caches: Dict[str, str] = {}  # cache_attr -> directory
        self._codec_wrappers: Dict[str, CodecMapping] = {}

    @staticmethod
    def _slug(text: str, repl: str = "_") -> str:
        return DiskCacheMixin._SLUG_RX.sub(repl, text)

    @staticmethod
    def _user_cache_root() -> Path:
        try:
            from platformdirs import user_cache_dir

            return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "diskcache"
        except Exception:
            if os.name == "nt":
                return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "diskcache"
            return Path.home() / ".cache" / "arbs" / "diskcache"

    @staticmethod
    def default_cache_path(stem: str, ext: str = "") -> str:
        safe = DiskCacheMixin._slug(stem)
        root = Path(DiskCacheMixin.CACHE_ROOT) if DiskCacheMixin.CACHE_ROOT else DiskCacheMixin._user_cache_root()
        dump_dir = root / "dump"
        try:
            dump_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            dump_dir = Path(tempfile.gettempdir()) / "arbs_diskcache_dump"
            dump_dir.mkdir(parents=True, exist_ok=True)
        return str((dump_dir / safe).resolve())

    @classmethod
    def _acquire_cache(cls, directory: str) -> diskcache.FanoutCache:
        with cls._REGISTRY_LOCK:
            cache = cls._CACHE_REGISTRY.get(directory)
            if cache is None:
                Path(directory).mkdir(parents=True, exist_ok=True)
                cache = diskcache.FanoutCache(
                    directory=directory,
                    shards=8,
                    size_limit=2**32,  # 4 GB
                    eviction_policy="least-recently-used",
                )
                cls._CACHE_REGISTRY[directory] = cache
            return cache

    def open_cache(
        self: T,
        *,
        cache_attr: str,
        path: str,
        encode: EncodeFn | None = None,
        decode: DecodeFn | None = None,
        force: bool | None = None,
    ) -> None:
        if force is None:
            force = self._force_refresh

        if force and cache_attr in self._dc_caches:
            old_dir = self._dc_caches.pop(cache_attr)
            if hasattr(self, cache_attr):
                delattr(self, cache_attr)

        if cache_attr in self._dc_caches:
            return

        cache = self._acquire_cache(path)

        if force:
            cache.clear()

        mapping: Any = cache
        if encode or decode:
            mapping = CodecMapping(cache, encode, decode)
            self._codec_wrappers[cache_attr] = mapping

        setattr(self, cache_attr, mapping)
        self._dc_caches[cache_attr] = path

    # Backward-compat aliases
    def zodb_open_cache(self: T, **kwargs: Any) -> None:
        self.open_cache(**kwargs)

    @contextlib.contextmanager
    def batched(self: T) -> Generator[None, None, None]:
        # DiskCache auto-commits; keep as no-op context manager for compatibility
        yield

    def zodb_commit(self: T) -> None:
        # DiskCache auto-commits; no-op for backward compatibility
        pass

    def close_cache(self: T) -> None:
        for attr in list(self._dc_caches):
            if hasattr(self, attr):
                delattr(self, attr)
        self._dc_caches.clear()
        self._codec_wrappers.clear()

    # Backward-compat alias
    def close_zodb(self: T) -> None:
        self.close_cache()

    @classmethod
    def diagnostics(cls) -> dict[str, int]:
        with cls._REGISTRY_LOCK:
            return {p: len(c) for p, c in cls._CACHE_REGISTRY.items()}
