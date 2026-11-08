'''
Turn raw IGDB / CheapShark JSON into the simplified shapes our API returns.

IGDB omits a field entirely when it has no value, so every lookup here uses
.get() with a fallback. Pure functions only: no network, no state.
'''

from datetime import datetime, timezone
from typing import Any

from .config import CHEAPSHARK_SITE_URL, IGDB_IMAGE_URL
from .schemas import (
    Deals,
    FilterOption,
    Filters,
    GameCard,
    GameDetail,
    Offer,
    PricePoint,
    RawJSON,
    StoreInfo,
)

CHEAPSHARK_REDIRECT_URL = 'https://www.cheapshark.com/redirect?dealID={deal_id}'
OFFICIAL_WEBSITE_TYPE = 1  # IGDB website type id for "Official Website"
STEAM_CATEGORY = 1         # old numeric external_games.category for Steam


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def image_url(image_id: str | None, size: str) -> str | None:
    '''
    Build an IGDB image URL.

    Args:
        image_id: IGDB image id, or None.
        size: IGDB size name, e.g. 'cover_big', 'screenshot_med' or '1080p'.

    Returns:
        The image URL, or None if there is no image id.
    '''
    return IGDB_IMAGE_URL.format(size=size, image_id=image_id) if image_id else None


def _first_image_id(items: list[RawJSON] | None) -> str | None:
    '''The image_id of the first cover/screenshot object, or None.'''
    return items[0].get('image_id') if items else None


def _names(items: list[RawJSON] | None) -> list[str]:
    '''The non-empty `name` of each object, e.g. genre or game mode names.'''
    return [item['name'] for item in items or [] if item.get('name')]


def _platform_names(platforms: list[RawJSON] | None) -> list[str]:
    '''Short labels like "PC" or "PS5", falling back to the full name.'''
    labels = (p.get('abbreviation') or p.get('name') for p in platforms or [])
    return [label for label in labels if label]


def _score(value: float | None) -> int | None:
    '''IGDB scores are floats like 88.4213; round to a whole number out of 100.'''
    return round(value) if value is not None else None


def _to_datetime(timestamp: int | None) -> datetime | None:
    '''Convert an IGDB date (Unix seconds, UTC) to an aware datetime.'''
    return datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp is not None else None


def _year(timestamp: int | None) -> int | None:
    '''The release year of an IGDB timestamp, or None.'''
    date = _to_datetime(timestamp)
    return date.year if date else None


def _iso_date(timestamp: int | None) -> str | None:
    '''An IGDB/CheapShark timestamp as 'YYYY-MM-DD' (UTC), or None.'''
    date = _to_datetime(timestamp)
    return date.strftime('%Y-%m-%d') if date else None


def _to_float(value: Any) -> float | None:
    '''CheapShark sends prices and savings as strings like "14.99"; None if unparsable.'''
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# /api/filters
# ---------------------------------------------------------------------------

def normalize_filters(genres: list[RawJSON], modes: list[RawJSON]) -> Filters:
    '''
    Build the /api/filters response.

    Args:
        genres: Raw IGDB /genres results.
        modes: Raw IGDB /game_modes results.

    Returns:
        {genres, modes}, each a list of {id, name} with unnamed entries dropped.
    '''
    def options(items: list[RawJSON]) -> list[FilterOption]:
        return [{'id': item['id'], 'name': item['name']} for item in items if item.get('name')]

    return {'genres': options(genres), 'modes': options(modes)}


# ---------------------------------------------------------------------------
# /api/search
# ---------------------------------------------------------------------------

def normalize_card(game: RawJSON) -> GameCard:
    '''
    Build one search result card.

    Args:
        game: One raw IGDB /games result requested with CARD_FIELDS.

    Returns:
        The card. Artwork is the first screenshot, else the cover, else None.
    '''
    screenshot = _first_image_id(game.get('screenshots'))
    cover = (game.get('cover') or {}).get('image_id')
    image = image_url(screenshot, 'screenshot_med') or image_url(cover, 'cover_big')

    return {
        'id': game['id'],
        'name': game.get('name', 'Untitled'),
        'year': _year(game.get('first_release_date')),
        'image': image,
        'rating': _score(game.get('total_rating')),
        'rating_count': game.get('total_rating_count', 0),
        'critics': _score(game.get('aggregated_rating')),
        'genres': _names(game.get('genres')),
        'platforms': _platform_names(game.get('platforms')),
        'modes': _names(game.get('game_modes')),
    }


# ---------------------------------------------------------------------------
# /api/game/<id>
# ---------------------------------------------------------------------------

def _companies(game: RawJSON, role: str) -> list[str]:
    '''Names of involved companies with the given role ('developer' or 'publisher').'''
    return [
        entry['company']['name']
        for entry in game.get('involved_companies') or []
        if entry.get(role) and (entry.get('company') or {}).get('name')
    ]


def _esrb(game: RawJSON) -> str | None:
    '''The ESRB rating (e.g. "M", "E10+") among all age ratings, or None.'''
    for rating in game.get('age_ratings') or []:
        if (rating.get('organization') or {}).get('name') == 'ESRB':
            return (rating.get('rating_category') or {}).get('rating')
    return None


def _official_website(game: RawJSON) -> str:
    '''The URL of the game's official website, or '' if IGDB lists none.'''
    for site in game.get('websites') or []:
        if site.get('type') == OFFICIAL_WEBSITE_TYPE and site.get('url'):
            return site['url']
    return ''


def steam_app_id(game: RawJSON) -> str | None:
    '''
    Find the game's Steam app id in IGDB external_games.

    IGDB is replacing the numeric `category` (1 = Steam) with
    `external_game_source`, so both are checked.

    Args:
        game: A raw IGDB /games result requested with DETAIL_FIELDS.

    Returns:
        The Steam app id, or None if the game is not on Steam.
    '''
    for entry in game.get('external_games') or []:
        source = (entry.get('external_game_source') or {}).get('name')
        if (source == 'Steam' or entry.get('category') == STEAM_CATEGORY) and entry.get('uid'):
            return entry['uid']
    return None


def normalize_detail(game: RawJSON) -> GameDetail:
    '''
    Build the game detail response, except for the prices.

    Args:
        game: A raw IGDB /games result requested with DETAIL_FIELDS.

    Returns:
        The detail fields. `deals` and `deals_error` are added by the service.
    '''
    screenshot_ids = [s['image_id'] for s in game.get('screenshots') or [] if s.get('image_id')]
    cover_id = (game.get('cover') or {}).get('image_id')
    hero_id = screenshot_ids[0] if screenshot_ids else None

    return {
        'id': game['id'],
        'name': game.get('name', 'Untitled'),
        'released': _iso_date(game.get('first_release_date')),
        'year': _year(game.get('first_release_date')),
        'image': image_url(hero_id, '1080p') or image_url(cover_id, 'cover_big'),
        'cover': image_url(cover_id, 'cover_big'),
        'description': game.get('summary') or game.get('storyline') or '',
        'website': _official_website(game),
        'developers': _companies(game, 'developer'),
        'publishers': _companies(game, 'publisher'),
        'genres': _names(game.get('genres')),
        'platforms': _platform_names(game.get('platforms')),
        'modes': _names(game.get('game_modes')),
        'esrb': _esrb(game),
        'rating': _score(game.get('total_rating')),
        'rating_count': game.get('total_rating_count', 0),
        'critics': _score(game.get('aggregated_rating')),
        'critics_count': game.get('aggregated_rating_count', 0),
        'screenshots': [
            {
                'id': image_id,
                'image': image_url(image_id, '1080p'),        # full size, for the lightbox
                'thumb': image_url(image_id, 'screenshot_med'),  # gallery thumbnail
            }
            for image_id in screenshot_ids
        ],
    }


def normalize_stores(stores: list[RawJSON]) -> dict[str, StoreInfo]:
    '''
    Index the CheapShark store list by id.

    Args:
        stores: Raw CheapShark /stores results.

    Returns:
        storeID (as a string) -> {name, icon}. Icon paths are made absolute,
        since CheapShark gives them relative to cheapshark.com.
    '''
    result: dict[str, StoreInfo] = {}
    for store in stores:
        icon = (store.get('images') or {}).get('icon')
        result[str(store['storeID'])] = {
            'name': store.get('storeName', 'Unknown store'),
            'icon': f'{CHEAPSHARK_SITE_URL}{icon}' if icon else None,
        }
    return result


def normalize_deals(data: RawJSON, stores: dict[str, StoreInfo]) -> Deals | None:
    '''
    Build the `deals` object from a CheapShark games?id= response.

    Args:
        data: Raw CheapShark games?id= response.
        stores: Output of normalize_stores(). May be empty if the store list
            failed; offers are still shown, labelled 'Store #<id>' and
            without icons.

    Returns:
        Offers sorted by price (the first one marked is_cheapest) plus the
        all-time low, or None if there are no offers with a valid price.
    '''
    offers: list[Offer] = []
    for deal in data.get('deals') or []:
        price = _to_float(deal.get('price'))
        if price is None:
            continue
        store_id = str(deal.get('storeID'))
        store = stores.get(store_id)
        savings = _to_float(deal.get('savings'))
        offers.append({
            'store': store['name'] if store else f'Store #{store_id}',
            'icon': store['icon'] if store else None,
            'price': price,
            'retail_price': _to_float(deal.get('retailPrice')),
            'savings': round(savings) if savings is not None else None,
            'url': CHEAPSHARK_REDIRECT_URL.format(deal_id=deal.get('dealID')),
            'is_cheapest': False,
        })

    if not offers:
        return None

    offers.sort(key=lambda offer: offer['price'])
    offers[0]['is_cheapest'] = True

    lowest = data.get('cheapestPriceEver') or {}
    lowest_price = _to_float(lowest.get('price'))
    cheapest_ever: PricePoint | None = (
        {'price': lowest_price, 'date': _iso_date(lowest.get('date'))}
        if lowest_price is not None else None
    )

    return {'cheapest_ever': cheapest_ever, 'offers': offers}
