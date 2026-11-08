'''
Turn raw IGDB / CheapShark JSON into the simplified shapes our API returns.

IGDB omits a field entirely when it has no value, so every lookup here uses
.get() with a fallback. Pure functions only: no network, no state.
'''

from datetime import datetime, timezone

from .config import CHEAPSHARK_SITE_URL, IGDB_IMAGE_URL

CHEAPSHARK_REDIRECT_URL = 'https://www.cheapshark.com/redirect?dealID={deal_id}'
OFFICIAL_WEBSITE_TYPE = 1  # IGDB website type id for "Official Website"
STEAM_CATEGORY = 1         # old numeric external_games.category for Steam


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def image_url(image_id, size):
    '''Build an IGDB image URL, e.g. size "cover_big" or "screenshot_med".'''
    return IGDB_IMAGE_URL.format(size=size, image_id=image_id) if image_id else None


def _first_image_id(items):
    return items[0].get('image_id') if items else None


def _names(items):
    return [item['name'] for item in items or [] if item.get('name')]


def _platform_names(platforms):
    '''Short labels like "PC" or "PS5", falling back to the full name.'''
    labels = (p.get('abbreviation') or p.get('name') for p in platforms or [])
    return [label for label in labels if label]


def _score(value):
    '''IGDB scores are floats like 88.4213; round to a whole number out of 100.'''
    return round(value) if value is not None else None


def _to_datetime(timestamp):
    # IGDB dates are Unix timestamps in seconds, in UTC.
    return datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp is not None else None


def _year(timestamp):
    date = _to_datetime(timestamp)
    return date.year if date else None


def _iso_date(timestamp):
    date = _to_datetime(timestamp)
    return date.strftime('%Y-%m-%d') if date else None


def _to_float(value):
    '''CheapShark sends prices and savings as strings like "14.99".'''
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# /api/filters
# ---------------------------------------------------------------------------

def normalize_filters(genres, modes):
    def options(items):
        return [{'id': item['id'], 'name': item['name']} for item in items if item.get('name')]

    return {'genres': options(genres), 'modes': options(modes)}


# ---------------------------------------------------------------------------
# /api/search
# ---------------------------------------------------------------------------

def normalize_card(game):
    '''One search result. Artwork: first screenshot, else cover, else None.'''
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

def _companies(game, role):
    '''Names of involved companies with the given role ("developer" or "publisher").'''
    return [
        entry['company']['name']
        for entry in game.get('involved_companies') or []
        if entry.get(role) and (entry.get('company') or {}).get('name')
    ]


def _esrb(game):
    '''The ESRB rating (e.g. "M", "E10+") among all age ratings, or None.'''
    for rating in game.get('age_ratings') or []:
        if (rating.get('organization') or {}).get('name') == 'ESRB':
            return (rating.get('rating_category') or {}).get('rating')
    return None


def _official_website(game):
    for site in game.get('websites') or []:
        if site.get('type') == OFFICIAL_WEBSITE_TYPE and site.get('url'):
            return site['url']
    return ''


def steam_app_id(game):
    '''
    The game's Steam app id from IGDB external_games, or None.

    IGDB is replacing the numeric `category` (1 = Steam) with
    `external_game_source`, so both are checked.
    '''
    for entry in game.get('external_games') or []:
        source = (entry.get('external_game_source') or {}).get('name')
        if (source == 'Steam' or entry.get('category') == STEAM_CATEGORY) and entry.get('uid'):
            return entry['uid']
    return None


def normalize_detail(game):
    '''Everything except the prices (deals are merged in by the service).'''
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


def normalize_stores(stores):
    '''storeID -> {name, icon}. Icon paths are relative to cheapshark.com.'''
    result = {}
    for store in stores:
        icon = (store.get('images') or {}).get('icon')
        result[str(store['storeID'])] = {
            'name': store.get('storeName', 'Unknown store'),
            'icon': f'{CHEAPSHARK_SITE_URL}{icon}' if icon else None,
        }
    return result


def normalize_deals(data, stores):
    '''
    Build the `deals` object from a CheapShark games?id= response, or return
    None if there are no offers. `stores` may be empty if the store list
    failed; offers are still shown, just without names and icons.
    '''
    offers = []
    for deal in data.get('deals') or []:
        price = _to_float(deal.get('price'))
        if price is None:
            continue
        store_id = str(deal.get('storeID'))
        store = stores.get(store_id, {})
        savings = _to_float(deal.get('savings'))
        offers.append({
            'store': store.get('name', f'Store #{store_id}'),
            'icon': store.get('icon'),
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
    cheapest_ever = (
        {'price': lowest_price, 'date': _iso_date(lowest.get('date'))}
        if lowest_price is not None else None
    )

    return {'cheapest_ever': cheapest_ever, 'offers': offers}
