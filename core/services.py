'''
The three backend operations behind /api/filters, /api/search and
/api/game/<id>. Each one checks the cache, runs independent upstream calls in
parallel, normalizes the results, and caches only complete answers.
'''

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from .cache import TTLCache, make_key
from .cheapshark import CheapSharkClient
from .config import FILTERS_TTL, GAME_TTL, MAX_GAME_ID, PAGE_SIZE, SEARCH_TTL, STORES_TTL
from .errors import NotFoundError, PriceLookupError, UpstreamError
from .igdb import FILTER_LIST_QUERY, IGDBClient, build_detail_query, build_search_queries
from .normalize import (
    normalize_card,
    normalize_deals,
    normalize_detail,
    normalize_filters,
    normalize_stores,
    steam_app_id,
)
from .schemas import Deals, Filters, GameDetail, RawJSON, SearchPage, StoreInfo

logger = logging.getLogger(__name__)

PRICES_UNAVAILABLE = 'Prices unavailable right now.'


class GameExplorerService:
    '''
    Combines IGDB, CheapShark and the cache into the three API operations.
    One instance is shared by every request thread.
    '''

    def __init__(self, igdb: IGDBClient, cheapshark: CheapSharkClient, cache: TTLCache) -> None:
        '''
        Args:
            igdb: Client for game data.
            cheapshark: Client for store prices.
            cache: Shared cache for complete responses and the store list.
        '''
        self._igdb = igdb
        self._cheapshark = cheapshark
        self._cache = cache

    # ----- /api/filters -------------------------------------------------------

    def filters(self) -> Filters:
        '''
        Genres and game modes for the dropdowns, cached for 24 hours.

        Raises:
            UpstreamError: IGDB failed (HTTP 502).
        '''
        key = make_key('filters')
        cached: Filters | None = self._cache.get(key)
        if cached is not None:
            return cached

        # The two lists are independent, so fetch them at the same time.
        with ThreadPoolExecutor(max_workers=2) as pool:
            genres = pool.submit(self._igdb.post, 'genres', FILTER_LIST_QUERY)
            modes = pool.submit(self._igdb.post, 'game_modes', FILTER_LIST_QUERY)
            result = normalize_filters(genres.result(), modes.result())

        self._cache.set(key, result, FILTERS_TTL)
        return result

    # ----- /api/search --------------------------------------------------------

    def search(
        self,
        query: str,
        genre: str | None,
        mode: str | None,
        ordering: str | None,
        page: int,
    ) -> SearchPage:
        '''
        One page of search results, cached for 15 minutes.

        All arguments must already be validated by parse_search_args().

        Args:
            query: Search text.
            genre: IGDB genre id, or None.
            mode: IGDB game mode id, or None.
            ordering: One of ORDERINGS, or None for relevance.
            page: 1-based page number.

        Returns:
            {count, page, has_next, results}. count is None if only the count
            query failed; such a partial page is not cached.

        Raises:
            UpstreamError: The results query failed (HTTP 502).
        '''
        key = make_key('search', query=query.casefold(), genre=genre, mode=mode,
                       ordering=ordering, page=page)
        cached: SearchPage | None = self._cache.get(key)
        if cached is not None:
            return cached

        results_query, count_query = build_search_queries(query, genre, mode, ordering, page)

        # The results and the total count are independent queries.
        with ThreadPoolExecutor(max_workers=2) as pool:
            results_future = pool.submit(self._igdb.post, 'games', results_query)
            count_future = pool.submit(self._igdb.post, 'games/count', count_query)
            games = results_future.result()  # without results there is nothing to show
            count = self._count_or_none(count_future)

        results = [normalize_card(game) for game in games]
        offset = (page - 1) * PAGE_SIZE
        if count is not None:
            has_next = offset + len(results) < count
        else:
            has_next = len(results) == PAGE_SIZE  # a full page suggests there may be more

        response: SearchPage = {'count': count, 'page': page, 'has_next': has_next, 'results': results}
        if count is not None:  # don't cache a partial answer for 15 minutes
            self._cache.set(key, response, SEARCH_TTL)
        return response

    @staticmethod
    def _count_or_none(future: Future[Any]) -> int | None:
        '''
        Read the total from a /games/count future.

        The count is optional: if it fails, the results are still returned.

        Returns:
            The total number of matches, or None if the query failed.
        '''
        try:
            return int(future.result()['count'])
        except (UpstreamError, KeyError, TypeError, ValueError):
            logger.warning('IGDB count query failed; returning count=null')
            return None

    # ----- /api/game/<id> -----------------------------------------------------

    def game(self, game_id: int) -> GameDetail:
        '''
        Merged IGDB details and CheapShark prices, cached for 15 minutes.

        Args:
            game_id: IGDB game id.

        Returns:
            The detail response. If CheapShark failed, deals is None,
            deals_error holds a message, and the response is not cached.

        Raises:
            NotFoundError: No game has this id (HTTP 404).
            UpstreamError: IGDB failed (HTTP 502).
        '''
        if game_id > MAX_GAME_ID:
            raise NotFoundError('Game not found.')

        key = make_key('game', id=game_id)
        cached: GameDetail | None = self._cache.get(key)
        if cached is not None:
            return cached

        # The IGDB details and the CheapShark store list don't depend on each
        # other. The price lookup does depend on the details (it needs the
        # Steam id and title), so it runs afterwards.
        with ThreadPoolExecutor(max_workers=2) as pool:
            details_future = pool.submit(self._igdb.post, 'games', build_detail_query(game_id))
            stores_future = pool.submit(self._stores)
            games = details_future.result()  # IGDB failure -> UpstreamError -> 502
            stores = stores_future.result()  # never raises; {} on failure

        if not games:
            raise NotFoundError('Game not found.')

        raw = games[0]
        result = normalize_detail(raw)
        result['deals'], result['deals_error'] = self._deals(raw, stores)

        # If CheapShark failed, don't cache: one blip would otherwise mean
        # 15 minutes of "Prices unavailable" after it recovers.
        if result.get('deals_error') is None:
            self._cache.set(key, result, GAME_TTL)
        return result

    def _stores(self) -> dict[str, StoreInfo]:
        '''
        CheapShark storeID -> {name, icon}, cached for 24 hours.

        Never raises: returns {} if CheapShark failed, since store names and
        icons are cosmetic.
        '''
        key = make_key('stores')
        cached: dict[str, StoreInfo] | None = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            stores = normalize_stores(self._cheapshark.stores())
        except PriceLookupError:
            return {}  # cosmetic only: prices can still be shown without store names
        self._cache.set(key, stores, STORES_TTL)
        return stores

    def _deals(self, raw_game: RawJSON, stores: dict[str, StoreInfo]) -> tuple[Deals | None, str | None]:
        '''
        Look up a game's prices on CheapShark.

        Args:
            raw_game: The raw IGDB detail result (for its Steam id and name).
            stores: Output of _stores().

        Returns:
            (deals, deals_error): (deals, None) on success, (None, None) when
            the game has no price data, and (None, message) if CheapShark failed.
        '''
        try:
            cheapshark_id = self._cheapshark.find_game_id(steam_app_id(raw_game), raw_game.get('name'))
            if not cheapshark_id:
                return None, None  # normal for console exclusives
            data = self._cheapshark.game(cheapshark_id)
            return (normalize_deals(data, stores) if data else None), None
        except PriceLookupError:
            return None, PRICES_UNAVAILABLE
