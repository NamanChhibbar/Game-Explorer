'''Thread-safe sliding-window rate limiter.'''

import threading
import time
from collections import deque


class RateLimiter:
    '''
    Allows at most `max_calls` calls to start within any `period` seconds.

    IGDB allows 4 requests per second per set of credentials. A search fires
    two requests at once, and several users (or a burst of Load more clicks)
    can easily exceed the limit and get HTTP 429. Instead of failing, each
    caller waits here until a slot in the window is free.
    '''

    def __init__(self, max_calls, period=1.0):
        self._max_calls = max_calls
        self._period = period
        self._calls = deque()  # start times of recent calls, oldest first
        self._lock = threading.Lock()

    def acquire(self):
        '''Block until the call may proceed, then record it.'''
        while True:
            with self._lock:
                now = time.monotonic()
                # Forget calls that have left the window.
                while self._calls and now - self._calls[0] >= self._period:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                wait = self._period - (now - self._calls[0])
            # Sleep outside the lock so other threads can check in meanwhile.
            time.sleep(wait)
