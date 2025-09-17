from typing import Any, Callable, MutableMapping

from persistent.mapping import PersistentMapping

EncodeFn = Callable[[Any], Any]
DecodeFn = Callable[[Any], Any]


class CodecMapping(MutableMapping):
    def __init__(self, backing: PersistentMapping, enc: EncodeFn, dec: DecodeFn):
        self._b, self._enc, self._dec = backing, enc or (lambda x: x), dec or (lambda x: x)

    def __getitem__(self, k):
        return self._dec(self._b[k])

    def __setitem__(self, k, v):
        if k and v:
            self._b[k] = self._enc(v)

    def __delitem__(self, k):
        del self._b[k]

    def __iter__(self):
        return iter(self._b)

    def __len__(self):
        return len(self._b)

    def __contains__(self, k):
        return k in self._b

    def clear(self):
        self._b.clear()

    @property
    def raw(self):
        return self._b
