'''
CheapShark client: store list, matching an IGDB game to a CheapShark game,
and that game's current deals. No API key is needed, but every request must
carry a descriptive User-Agent (set on the shared session).
'''

import logging
import re

import requests

from .config import CHEAPSHARK_BASE_URL, CHEAPSHARK_TIMEOUT
from .errors import PriceLookupError

logger = logging.getLogger(__name__)


class CheapSharkClient:
    def __init__(self, session):
        self._session = session

    def stores(self):
        '''Raw store list: [{storeID, storeName, images: {icon}}, ...].'''
        return self._get('stores', expect=list)

    def find_game_id(self, steam_app_id, title):
        '''
        Return the CheapShark gameID for a game, or None if it has no prices.

        A Steam app id is an exact match, so try it first. Otherwise (or if
        CheapShark doesn't know that id) search by title and accept only a
        title that matches; taking the first fuzzy result could show prices
        for a different game or a DLC.
        '''
        if steam_app_id:
            matches = self._get('games', {'steamAppID': steam_app_id}, expect=list)
            if matches and isinstance(matches[0], dict) and matches[0].get('gameID'):
                return matches[0]['gameID']

        if title:
            matches = self._get('games', {'title': title, 'limit': 5}, expect=list)
            return pick_title_match(matches, title)

        return None

    def game(self, cheapshark_id):
        '''
        Raw game info: {info, cheapestPriceEver, deals: [...]}, or None.
        CheapShark answers an unknown id with an empty list, which just means
        there is no price data.
        '''
        data = self._get('games', {'id': cheapshark_id}, expect=(dict, list))
        return data if isinstance(data, dict) else None

    def _get(self, path, params=None, expect=(dict, list)):
        '''
        GET a CheapShark endpoint and return its JSON. Raises PriceLookupError
        on a timeout, an HTTP error, invalid JSON, or JSON of an unexpected
        type (e.g. an error object where a list was expected), so callers
        never crash on a surprising 200 response.
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


def _simplify_title(title):
    '''Lowercase and drop ™/®/punctuation so "DOOM™" matches "Doom".'''
    return re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()


def pick_title_match(matches, title):
    '''Prefer an exact (case-insensitive) title, then one equal after simplifying.'''
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
