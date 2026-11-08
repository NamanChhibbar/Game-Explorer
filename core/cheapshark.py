'''
CheapShark client: store list, matching an IGDB game to a CheapShark game,
and that game's current deals. No API key is needed, but every request must
carry a descriptive User-Agent (set on the shared session).
'''

import logging
import re
from typing import Any

import requests

from .config import CHEAPSHARK_BASE_URL, CHEAPSHARK_TIMEOUT
from .errors import PriceLookupError
from .schemas import RawJSON

logger = logging.getLogger(__name__)


class CheapSharkClient:
    '''Read-only CheapShark API client. Every failure raises PriceLookupError.'''

    def __init__(self, session: requests.Session) -> None:
        '''
        Args:
            session: Shared HTTP session (it carries the required User-Agent).
        '''
        self._session = session

    def stores(self) -> list[RawJSON]:
        '''
        Fetch the raw store list.

        Returns:
            [{storeID, storeName, images: {icon}, ...}, ...]

        Raises:
            PriceLookupError: CheapShark failed or answered unexpectedly.
        '''
        return self._get('stores', expect=list)

    def find_game_id(self, steam_app_id: str | None, title: str | None) -> str | None:
        '''
        Find the CheapShark gameID for an IGDB game.

        A Steam app id is an exact match, so try it first. Otherwise (or if
        CheapShark doesn't know that id) search by title and accept only a
        title that matches; taking the first fuzzy result could show prices
        for a different game or a DLC.

        Args:
            steam_app_id: The game's Steam app id from IGDB, if any.
            title: The game's IGDB name, if any.

        Returns:
            The CheapShark gameID, or None if the game has no price data.

        Raises:
            PriceLookupError: CheapShark failed or answered unexpectedly.
        '''
        if steam_app_id:
            matches = self._get('games', {'steamAppID': steam_app_id}, expect=list)
            if matches and isinstance(matches[0], dict) and matches[0].get('gameID'):
                return matches[0]['gameID']

        if title:
            matches = self._get('games', {'title': title, 'limit': 5}, expect=list)
            return pick_title_match(matches, title)

        return None

    def game(self, cheapshark_id: str) -> RawJSON | None:
        '''
        Fetch a game's current deals.

        Args:
            cheapshark_id: A gameID from find_game_id().

        Returns:
            {info, cheapestPriceEver, deals: [...]}, or None for an unknown
            id (CheapShark answers those with an empty list, which just means
            there is no price data).

        Raises:
            PriceLookupError: CheapShark failed or answered unexpectedly.
        '''
        data = self._get('games', {'id': cheapshark_id}, expect=(dict, list))
        return data if isinstance(data, dict) else None

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        expect: type | tuple[type, ...] = (dict, list),
    ) -> Any:
        '''
        GET a CheapShark endpoint and return its parsed JSON.

        Args:
            path: Endpoint path relative to the API base, e.g. 'games'.
            params: Query string parameters.
            expect: Type(s) the JSON must have, checked with isinstance().

        Returns:
            The parsed JSON, guaranteed to be an instance of `expect`.

        Raises:
            PriceLookupError: On a timeout, an HTTP error, invalid JSON, or
                JSON of an unexpected type (e.g. an error object where a list
                was expected), so callers never crash on a surprising 200.
        '''
        try:
            response = self._session.get(
                f'{CHEAPSHARK_BASE_URL}/{path}', params=params, timeout=CHEAPSHARK_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            logger.warning('CheapShark /%s timed out after %ss', path, CHEAPSHARK_TIMEOUT)
            raise PriceLookupError('timeout') from None
        except requests.HTTPError:
            logger.error('CheapShark /%s returned %s: %s', path, response.status_code, response.text[:300])
            raise PriceLookupError('http error') from None
        except (requests.RequestException, ValueError) as exc:
            logger.error('CheapShark /%s failed: %s', path, type(exc).__name__)
            raise PriceLookupError('request failed') from None

        if not isinstance(data, expect):
            logger.error('CheapShark /%s returned an unexpected %s', path, type(data).__name__)
            raise PriceLookupError('unexpected response')
        return data


def _simplify_title(title: str) -> str:
    '''Lowercase and drop ™/®/punctuation so "DOOM™" matches "Doom".'''
    return re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()


def pick_title_match(matches: list[Any], title: str) -> str | None:
    '''
    Pick the CheapShark search result whose title matches the IGDB title.

    Prefers an exact (case-insensitive) title, then one equal after
    simplifying. Anything else is rejected rather than guessed.

    Args:
        matches: Raw results of games?title=; malformed entries are skipped.
        title: The IGDB game name.

    Returns:
        The matching gameID, or None.
    '''
    wanted = title.casefold()
    matches = [match for match in matches if isinstance(match, dict) and match.get('gameID')]
    for match in matches:
        if match.get('external', '').casefold() == wanted:
            return match.get('gameID')

    simple = _simplify_title(title)
    for match in matches:
        if _simplify_title(match.get('external', '')) == simple:
            return match.get('gameID')

    return None
