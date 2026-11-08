'''
IGDB access token handling (Twitch client-credentials flow).

The client id and secret are exchanged for a bearer token once; the token is
kept in memory and renewed shortly before it expires.
'''

import logging
import threading
import time

import requests

from .config import TOKEN_REFRESH_MARGIN, TOKEN_TIMEOUT, TWITCH_TOKEN_URL
from .errors import TokenError

logger = logging.getLogger(__name__)


class TokenStore:
    '''
    Holds one IGDB bearer token in memory and renews it shortly before expiry.

    Twitch tokens last about 60 days, so the credentials are exchanged once
    and the token is reused by every request. A threading.Lock makes sure
    that when several requests arrive together on a cold start (gunicorn runs
    8 threads), only one of them calls Twitch; the others wait and then reuse
    the token it stored.
    '''

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        session: requests.Session,
        refresh_margin: float = TOKEN_REFRESH_MARGIN,
    ) -> None:
        '''
        Args:
            client_id: Twitch/IGDB client id, or None if not configured.
            client_secret: Twitch/IGDB client secret, or None if not configured.
            session: Shared HTTP session used to call Twitch.
            refresh_margin: Seconds before expiry at which the token is renewed.
        '''
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session
        self._refresh_margin = refresh_margin
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0  # Unix time when the current token expires

    def get(self) -> str:
        '''
        Return a valid token, fetching a new one only if needed.

        Returns:
            A bearer token that is valid for at least refresh_margin seconds.

        Raises:
            TokenError: Twitch could not be reached or the credentials are missing.
        '''
        with self._lock:
            if self._token is not None and self._is_fresh():
                return self._token
            return self._fetch()

    def refresh(self, stale_token: str) -> str:
        '''
        Replace a token IGDB rejected with a 401, and return the new one.

        Takes the token the caller used, so if several threads hit a 401 at
        once, only the first one fetches; the rest see the token has already
        changed and reuse the new one.

        Args:
            stale_token: The token that IGDB rejected.

        Returns:
            A token different from stale_token.

        Raises:
            TokenError: Twitch could not be reached or the credentials are missing.
        '''
        with self._lock:
            if self._token is not None and self._token != stale_token:
                return self._token
            return self._fetch()

    def _is_fresh(self) -> bool:
        '''True if the stored token is not yet due for renewal. Call with the lock held.'''
        return time.time() < self._expires_at - self._refresh_margin

    def _fetch(self) -> str:
        '''
        Exchange the credentials for a new token, store it and return it.
        Call with the lock held.

        Raises:
            TokenError: With a generic message; details go to the log only.
        '''
        if not self._client_id or not self._client_secret:
            raise TokenError('The game database is not configured on the server.')

        try:
            # The credentials go in the form body, not the URL: requests puts
            # the URL in its exception messages, which would leak the secret.
            response = self._session.post(
                TWITCH_TOKEN_URL,
                data={
                    'client_id': self._client_id,
                    'client_secret': self._client_secret,
                    'grant_type': 'client_credentials',
                },
                timeout=TOKEN_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            token = str(payload['access_token'])
            expires_in = int(payload['expires_in'])  # a duration in seconds, not a timestamp
        except (requests.RequestException, ValueError, KeyError, TypeError):
            # Log the traceback for debugging (it holds no credentials, since they
            # were sent in the body), but give the client only a generic message.
            logger.exception('Could not obtain an IGDB access token')
            raise TokenError('Could not connect to the game database. Please try again later.') from None

        self._token = token
        self._expires_at = time.time() + expires_in
        logger.info('Obtained new IGDB access token (valid for %d days)', expires_in // 86400)
        return token
