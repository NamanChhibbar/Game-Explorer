'''Thread-safe in-memory cache with a per-entry time-to-live and a size limit.'''

import threading
import time
from collections import OrderedDict
from collections.abc import Hashable
from typing import Any

from .config import CACHE_MAX_ENTRIES

# (namespace, ((param, value), ...)) - see make_key().
CacheKey = tuple[str, tuple[tuple[str, Hashable], ...]]


def make_key(namespace: str, **params: Hashable) -> CacheKey:
    '''
    Build a cache key from every parameter that affects a result.

    Sorting the items makes the key independent of argument order, and the
    namespace keeps e.g. a search and a game lookup from ever colliding.

    Args:
        namespace: Kind of data, e.g. 'search' or 'game'.
        **params: Every input that changes the result. Values must be hashable.

    Returns:
        A hashable tuple usable as a TTLCache key.
    '''
    return (namespace, tuple(sorted(params.items())))


class TTLCache:
    '''
    Maps keys to (value, expires_at). Expired entries are dropped when read.
    When full, the least recently used entry is evicted (the OrderedDict is
    kept in usage order). A lock guards it because gunicorn serves requests
    on several threads that all share this one cache.
    '''

    def __init__(self, max_entries: int = CACHE_MAX_ENTRIES) -> None:
        '''
        Args:
            max_entries: Size limit; beyond it the least recently used entry is evicted.
        '''
        self._max_entries = max_entries
        self._data: OrderedDict[CacheKey, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: CacheKey) -> Any:
        '''
        Look up a value and mark it as recently used.

        Args:
            key: A key built with make_key().

        Returns:
            The cached value, or None if it is missing or expired.
        '''
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() >= expires_at:
                del self._data[key]
                return None
            self._data.move_to_end(key)  # mark as recently used
            return value

    def set(self, key: CacheKey, value: Any, ttl: float) -> None:
        '''
        Store a value, evicting the least recently used entries if full.

        Args:
            key: A key built with make_key().
            value: Data to cache. Must not be None (None means "missing" to get()).
            ttl: Seconds until the entry expires.
        '''
        with self._lock:
            self._data[key] = (value, time.time() + ttl)
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        '''Number of stored entries, including expired ones not yet read.'''
        with self._lock:
            return len(self._data)
