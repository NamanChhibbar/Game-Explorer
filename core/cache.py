'''Thread-safe in-memory cache with a per-entry time-to-live and a size limit.'''

import threading
import time
from collections import OrderedDict

from .config import CACHE_MAX_ENTRIES


def make_key(namespace, **params):
    '''
    Build a cache key from every parameter that affects a result.

    Sorting the items makes the key independent of argument order, and the
    namespace keeps e.g. a search and a game lookup from ever colliding.
    '''
    return (namespace, tuple(sorted(params.items())))


class TTLCache:
    '''
    Maps keys to (value, expires_at). Expired entries are dropped when read.
    When full, the least recently used entry is evicted (the OrderedDict is
    kept in usage order). A lock guards it because gunicorn serves requests
    on several threads that all share this one cache.
    '''

    def __init__(self, max_entries=CACHE_MAX_ENTRIES):
        self._max_entries = max_entries
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        '''Return the cached value, or None if it is missing or expired.'''
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

    def set(self, key, value, ttl):
        '''Store a value for ttl seconds, evicting the oldest entries if full.'''
        with self._lock:
            self._data[key] = (value, time.time() + ttl)
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def __len__(self):
        with self._lock:
            return len(self._data)
