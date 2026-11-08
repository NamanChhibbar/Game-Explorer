'''
Shapes of the JSON the API returns, written as TypedDicts.

These are type hints only: a TypedDict is a plain dict at runtime. They
document every field the frontend relies on, and let a type checker catch a
misspelled key in the normalizers or the service.
'''

from typing import Any, NotRequired, TypedDict

# One raw JSON object from IGDB or CheapShark, before normalizing. Its fields
# depend on the query, and IGDB leaves out empty ones, so it stays loosely typed.
RawJSON = dict[str, Any]


# --- GET /api/filters ------------------------------------------------------

class FilterOption(TypedDict):
    '''One genre or game mode in a dropdown.'''

    id: int
    name: str


class Filters(TypedDict):
    '''Response body of GET /api/filters.'''

    genres: list[FilterOption]
    modes: list[FilterOption]


# --- GET /api/search -------------------------------------------------------

class GameCard(TypedDict):
    '''One search result. Scores are whole numbers out of 100.'''

    id: int
    name: str
    year: int | None
    image: str | None
    rating: int | None
    rating_count: int
    critics: int | None
    genres: list[str]
    platforms: list[str]
    modes: list[str]


class SearchPage(TypedDict):
    '''Response body of GET /api/search. count is None if the count query failed.'''

    count: int | None
    page: int
    has_next: bool
    results: list[GameCard]


# --- GET /api/game/<id> ----------------------------------------------------

class Screenshot(TypedDict):
    '''One screenshot: full size for the lightbox, a thumbnail for the gallery.'''

    id: str
    image: str | None
    thumb: str | None


class StoreInfo(TypedDict):
    '''Display name and absolute icon URL of a CheapShark store.'''

    name: str
    icon: str | None


class Offer(TypedDict):
    '''One store's current price for a game.'''

    store: str
    icon: str | None
    price: float
    retail_price: float | None
    savings: int | None
    url: str
    is_cheapest: bool


class PricePoint(TypedDict):
    '''A price and the ISO date (YYYY-MM-DD) it was seen.'''

    price: float
    date: str | None


class Deals(TypedDict):
    '''Store offers sorted by price, cheapest first, plus the all-time low.'''

    cheapest_ever: PricePoint | None
    offers: list[Offer]


class GameDetail(TypedDict):
    '''
    Response body of GET /api/game/<id>.

    normalize_detail() fills everything except deals and deals_error, which
    the service adds after the CheapShark lookup.
    '''

    id: int
    name: str
    released: str | None
    year: int | None
    image: str | None
    cover: str | None
    description: str
    website: str
    developers: list[str]
    publishers: list[str]
    genres: list[str]
    platforms: list[str]
    modes: list[str]
    esrb: str | None
    rating: int | None
    rating_count: int
    critics: int | None
    critics_count: int
    screenshots: list[Screenshot]
    deals: NotRequired[Deals | None]
    deals_error: NotRequired[str | None]
