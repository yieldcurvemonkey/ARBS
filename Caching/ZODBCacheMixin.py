import contextlib
import functools
import os
import re
import tempfile
import threading
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, Generator, List, MutableMapping, Tuple, TypeVar

import transaction
from BTrees.OOBTree import OOBTree  # type: ignore
from persistent.mapping import PersistentMapping
from zc.lockfile import LockError
from ZODB import DB, Connection
from ZODB.DemoStorage import DemoStorage
from ZODB.FileStorage import FileStorage

from Caching.CodecMapping import CodecMapping

EncodeFn = Callable[[Any], Any]
DecodeFn = Callable[[Any], Any]
T = TypeVar("T", bound="ZODBCacheMixin")


class _DBHandle:
    __slots__ = ("db", "storage", "refcnt", "_conns", "_lock", "_pool_cap")

    def __init__(self, db: DB, storage: FileStorage):
        self.db: DB = db
        self.storage: FileStorage = storage
        self.refcnt: int = 0
        self._conns: List[Connection] = []  # type: ignore
        self._lock = threading.Lock()
        self._pool_cap = max(1, int(getattr(db, "pool_size", 7)))

    def get_conn(self) -> Connection:
        with self._lock:
            if self._conns:
                return self._conns.pop()
        return self.db.open(transaction_manager=transaction.manager)  # type: ignore[arg‑type]

    def release_conn(self, conn: Connection) -> None:
        with self._lock:
            if len(self._conns) >= self._pool_cap:
                conn.close()
            else:
                self._conns.append(conn)

    def incref(self) -> None:  # noqa: D401
        """Increment reference count."""
        self.refcnt += 1

    def decref(self) -> None:
        self.refcnt -= 1
        if self.refcnt == 0:
            while self._conns:
                self._conns.pop().close()
            self.db.close()
            self.storage.close()


class ZODBCacheMixin:
    _DB_REGISTRY: Dict[str, _DBHandle] = {}
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

        self._z_conns: Dict[str, Tuple[Connection, _DBHandle]] = {}  # type: ignore
        self._codec_wrappers: Dict[str, CodecMapping] = {}

    @classmethod
    def _open_filestorage(cls, path: str) -> FileStorage:
        try:
            return FileStorage(path)
        except LockError:
            try:
                ro = FileStorage(path, read_only=True)
            except Exception:
                raise
            return DemoStorage(base=ro)

    @functools.lru_cache(maxsize=128)
    def _slug(text: str, repl: str = "_") -> str:  # noqa: N805 – staticmethod lru‑cached
        return ZODBCacheMixin._SLUG_RX.sub(repl, text)

    @staticmethod
    def _user_cache_root() -> Path:
        try:
            from platformdirs import user_cache_dir

            return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "zodb"
        except Exception:
            if os.name == "nt":
                return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "zodb"
            return Path.home() / ".cache" / "arbs" / "zodb"

    @staticmethod
    def default_cache_path(stem: str, ext: str = ".fs") -> str:
        safe = ZODBCacheMixin._slug(stem)
        root = Path(ZODBCacheMixin.CACHE_ROOT) if ZODBCacheMixin.CACHE_ROOT else ZODBCacheMixin._user_cache_root()
        dump_dir = root / "dump"
        try:
            dump_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            dump_dir = Path(tempfile.gettempdir()) / "arbs_zodb_dump"
            dump_dir.mkdir(parents=True, exist_ok=True)
        return str((dump_dir / f"{safe}{ext}").resolve())

    @classmethod
    def _acquire_db(cls, path: str) -> _DBHandle:
        with cls._REGISTRY_LOCK:
            handle = cls._DB_REGISTRY.get(path)
            if handle is None:
                storage = cls._open_filestorage(path)
                db = DB(storage, pool_size=32, large_record_size=1 << 30)
                handle = _DBHandle(db, storage)
                cls._DB_REGISTRY[path] = handle
            handle.incref()
            return handle

    @classmethod
    def _release_db(cls, path: str) -> None:
        with cls._REGISTRY_LOCK:
            handle = cls._DB_REGISTRY.get(path)
            if handle is None:
                return
            handle.decref()
            if handle.refcnt == 0:
                del cls._DB_REGISTRY[path]

    def zodb_open_cache(
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

        if force and cache_attr in self._z_conns:
            conn, handle = self._z_conns.pop(cache_attr)
            handle.release_conn(conn)

            storage = handle.storage
            db_path = None
            if isinstance(storage, FileStorage):
                db_path = storage._file_name
            elif isinstance(storage, DemoStorage) and hasattr(storage, "_base"):
                db_path = getattr(storage._base, "_file_name", None)

            if db_path:
                self._release_db(db_path)

            delattr(self, cache_attr)

        if cache_attr in self._z_conns:
            return

        handle = self._acquire_db(path)
        conn = handle.get_conn()
        root = conn.root()

        if force or cache_attr not in root:
            container: MutableMapping[Any, Any]
            container = OOBTree() if self._use_btree else PersistentMapping()
            root[cache_attr] = container
            transaction.commit()
        mapping: MutableMapping[Any, Any] = root[cache_attr]

        if encode or decode:
            mapping = CodecMapping(mapping, encode, decode)
            self._codec_wrappers[cache_attr] = mapping  # type: ignore[arg‑type]

        setattr(self, cache_attr, mapping)
        self._z_conns[cache_attr] = (conn, handle)

    @contextlib.contextmanager
    def batched(self: T) -> Generator[None, None, None]:
        try:
            yield
            transaction.commit()
        except Exception:  # pragma: no cover – re‑raise after abort
            transaction.abort()
            raise

    def zodb_commit(self: T) -> None:
        transaction.commit()

    def close_zodb(self: T) -> None:
        with contextlib.suppress(Exception):
            transaction.abort()

        for attr, (conn, handle) in list(self._z_conns.items()):
            handle.release_conn(conn)

            storage = handle.storage
            path = None

            if isinstance(storage, FileStorage):
                path = storage._file_name
            elif isinstance(storage, DemoStorage) and hasattr(storage, "_base"):
                path = getattr(storage._base, "_file_name", None)

            if path:
                self._release_db(path)

            delattr(self, attr)

        self._z_conns.clear()
        self._codec_wrappers.clear()

    @classmethod
    def diagnostics(cls) -> MappingProxyType[str, int]:
        with cls._REGISTRY_LOCK:
            return MappingProxyType({p: h.refcnt for p, h in cls._DB_REGISTRY.items()})
