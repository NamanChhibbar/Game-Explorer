'''
IGDB client and query builders.

Every IGDB request is a POST whose body is a plain-text Apicalypse query
(not JSON, not URL parameters), sent with a Client-ID and a bearer token.
'''

import logging
import time

import requests

from .config import (
    IGDB_BASE_URL,
    IGDB_GAME_TYPES,
    IGDB_MAX_REQUESTS_PER_SECOND,
    IGDB_RATE_LIMIT_RETRY_DELAY,
    IGDB_TIMEOUT,
    PAGE_SIZE,
)
from .errors import UpstreamError
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = 'The game database is unavailable right now. Please try again later.'
TIMEOUT_MESSAGE = 'The game database took too long to respond. Please try again.'


class IGDBClient:
    '''Sends Apicalypse queries to IGDB, handling the token and retries.'''

    def __init__(self, client_id, token_store, session):
        self._client_id = client_id
        self._tokens = token_store
        self._session = session
        self._limiter = RateLimiter(IGDB_MAX_REQUESTS_PER_SECOND, period=1.0)

    def post(self, endpoint, body):
        '''
        Run one query and return the parsed JSON (a list, or a dict for /count).

        Every request first waits on the rate limiter (IGDB allows 4 per
        second). Retries once on 401 with a fresh token (the token may have
        been revoked before its expiry) and once on 429 after a pause, in case
        the limit was hit anyway. Any other failure raises UpstreamError.
        '''
        token = self._tokens.get()
        response = self._send(endpoint, body, token)

        if response.status_code == 401:
            token = self._tokens.refresh(token)
            response = self._send(endpoint, body, token)

        if response.status_code == 429:
            time.sleep(IGDB_RATE_LIMIT_RETRY_DELAY)
            response = self._send(endpoint, body, token)

        if not response.ok:
            # Log the body: IGDB explains syntax errors there. It never
            # contains our credentials, and it is not sent to the client.
            logger.error('IGDB /%s returned %s: %s', endpoint, response.status_code, response.text[:500])
            raise UpstreamError(UNAVAILABLE_MESSAGE)

        try:
            return response.json()
        except ValueError:
            logger.error('IGDB /%s returned invalid JSON', endpoint)
            raise UpstreamError(UNAVAILABLE_MESSAGE) from None

    def _send(self, endpoint, body, token):
        self._limiter.acquire()
        try:
            return self._session.post(
                f'{IGDB_BASE_URL}/{endpoint}',
                headers={
                    'Client-ID': self._client_id,
                    'Authorization': f'Bearer {token}',
                    'Accept': 'application/json',
                },
                data=body.encode('utf-8'),
                timeout=IGDB_TIMEOUT,
            )
        except requests.Timeout:
            logger.warning('IGDB /%s timed out after %ss', endpoint, IGDB_TIMEOUT)
            raise UpstreamError(TIMEOUT_MESSAGE) from None
        except requests.RequestException as exc:
            logger.error('IGDB /%s request failed: %s', endpoint, type(exc).__name__)
            raise UpstreamError(UNAVAILABLE_MESSAGE) from None


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

FILTER_LIST_QUERY = 'fields name; sort name asc; limit 500;'

CARD_FIELDS = ', '.join([
    'name', 'first_release_date',
    'total_rating', 'total_rating_count',
    'aggregated_rating', 'aggregated_rating_count',
    'cover.image_id', 'screenshots.image_id',
    'genres.name', 'platforms.abbreviation', 'platforms.name', 'game_modes.name',
])

DETAIL_FIELDS = ', '.join([
    CARD_FIELDS,
    'summary', 'storyline',
    'involved_companies.company.name', 'involved_companies.developer', 'involved_companies.publisher',
    'age_ratings.organization.name', 'age_ratings.rating_category.rating',
    'external_games.uid', 'external_games.category', 'external_games.external_game_source.name',
    'websites.url', 'websites.type',
])

# ordering value -> (sort clause, extra where condition or None).
# The extra conditions drop games with no value for the sort field, and stop
# obscure games with one or two ratings from filling the top of the list.
SORTS = {
    'rating': ('total_rating desc', 'total_rating != null & total_rating_count >= 3'),
    'critics': ('aggregated_rating desc', 'aggregated_rating != null & aggregated_rating_count >= 2'),
    'newest': ('first_release_date desc', 'first_release_date != null & first_release_date <= {now}'),
    'name': ('name asc', None),
}


def escape(term):
    '''
    Escape a user's search term for use inside an Apicalypse "quoted string".

    Backslashes first, then quotes, so a title like  Say "Hi"  cannot close
    the string early and inject extra clauses into the query.
    '''
    return term.replace('\\', '\\\\').replace('"', '\\"')


def build_search_queries(term, genre_id=None, mode_id=None, ordering=None, page=1):
    '''
    Return (results_query, count_query) for one page of search results.

    `search "term";` ranks by relevance and ignores any sort clause, so when
    the user picks a sort order we switch to a substring match instead:
    `where name ~ *"term"*;`, which can be sorted.
    '''
    safe = escape(term)
    conditions = [
        'version_parent = null',  # skip editions/versions of the same game
        f'game_type = ({",".join(str(t) for t in IGDB_GAME_TYPES)})',  # games, not DLC/mods/packs
    ]
    if genre_id:
        conditions.append(f'genres = ({int(genre_id)})')
    if mode_id:
        conditions.append(f'game_modes = ({int(mode_id)})')

    if ordering:
        sort_clause, extra = SORTS[ordering]
        conditions.insert(0, f'name ~ *"{safe}"*')
        if extra:
            conditions.append(extra.format(now=int(time.time())))
        head = ''
        tail = f' sort {sort_clause};'
    else:
        head = f'search "{safe}"; '
        tail = ''

    where = f'where {" & ".join(conditions)};'
    offset = (page - 1) * PAGE_SIZE
    results_query = f'{head}fields {CARD_FIELDS}; {where}{tail} limit {PAGE_SIZE}; offset {offset};'
    count_query = f'{head}{where}'
    return results_query, count_query


def build_detail_query(game_id):
    return f'fields {DETAIL_FIELDS}; where id = {int(game_id)}; limit 1;'
