'''
The three backend operations behind /api/filters, /api/search and
/api/game/<id>. Each one checks the cache, runs independent upstream calls in
parallel, normalizes the results, and caches only complete answers.
'''

import logging
from concurrent.futures import ThreadPoolExecutor

from .cache import make_key
from .config import FILTERS_TTL, GAME_TTL, MAX_GAME_ID, PAGE_SIZE, SEARCH_TTL, STORES_TTL
from .errors import NotFoundError, PriceLookupError, UpstreamError
from .igdb import FILTER_LIST_QUERY, build_detail_query, build_search_queries
from .normalize import (
    normalize_card,
    normalize_deals,
    normalize_detail,
    normalize_filters,
    normalize_stores,
    steam_app_id,
)

logger = logging.getLogger(__name__)

PRICES_UNAVAILABLE = 'Prices unavailable right now.'


class GameExplorerService:
    def __init__(self, igdb, cheapshark, cache):
        self._igdb = igdb
        self._cheapshark = cheapshark
        self._cache = cache

    # ----- /api/filters -------------------------------------------------------

    def filters(self):
        '''Genres and game modes for the dropdowns (cached for 24 hours).'''
        key = make_key('filters')
        cached = self._cache.get(key)
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

    def search(self, query, genre, mode, ordering, page):
        '''One page of results. Arguments must already be validated.'''
        key = make_key('search', query=query.casefold(), genre=genre, mode=mode,
                       ordering=ordering, page=page)
        cached = self._cache.get(key)
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

        response = {'count': count, 'page': page, 'has_next': has_next, 'results': results}
        if count is not None:  # don't cache a partial answer for 15 minutes
            self._cache.set(key, response, SEARCH_TTL)
        return response

    @staticmethod
    def _count_or_none(future):
        '''The count is optional: if it fails, the results are still returned.'''
        try:
            return int(future.result()['count'])
        except (UpstreamError, KeyError, TypeError, ValueError):
            logger.warning('IGDB count query failed; returning count=null')
            return None

    # ----- /api/game/<id> -----------------------------------------------------

    def game(self, game_id):
        '''Merged IGDB details + CheapShark prices.'''
        if game_id > MAX_GAME_ID:
            raise NotFoundError('Game not found.')

        key = make_key('game', id=game_id)
        cached = self._cache.get(key)
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
        if result['deals_error'] is None:
            self._cache.set(key, result, GAME_TTL)
        return result

    def _stores(self):
        '''CheapShark storeID -> {name, icon}, cached for 24 hours.'''
        key = make_key('stores')
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            stores = normalize_stores(self._cheapshark.stores())
        except PriceLookupError:
            return {}  # cosmetic only: prices can still be shown without store names
        self._cache.set(key, stores, STORES_TTL)
        return stores

    def _deals(self, raw_game, stores):
        '''Return (deals, deals_error). deals is None when there is no price data.'''
        try:
            cheapshark_id = self._cheapshark.find_game_id(steam_app_id(raw_game), raw_game.get('name'))
            if not cheapshark_id:
                return None, None  # normal for console exclusives
            data = self._cheapshark.game(cheapshark_id)
            return (normalize_deals(data, stores) if data else None), None
        except PriceLookupError:
            return None, PRICES_UNAVAILABLE
