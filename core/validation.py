'''Validation and whitelisting of /api/search query parameters.'''

from collections.abc import Callable, Mapping

from .config import MAX_QUERY_LENGTH, ORDERINGS
from .errors import ValidationError
from .schemas import Filters

# (query, genre, mode, ordering, page) - the arguments of GameExplorerService.search().
SearchArgs = tuple[str, str | None, str | None, str | None, int]


def parse_search_args(args: Mapping[str, str], get_filters: Callable[[], Filters]) -> SearchArgs:
    '''
    Validate request.args for /api/search and return clean values.

    Args:
        args: The query string, e.g. Flask's request.args.
        get_filters: Returns the /api/filters data. It is only called when a
            genre or mode is given, since that's the only time the whitelist
            is needed (and it's cached after the first call).

    Returns:
        (query, genre, mode, ordering, page). genre, mode and ordering are
        None when omitted; page defaults to 1.

    Raises:
        ValidationError: A parameter is missing or invalid (HTTP 400).
    '''
    # Collapse runs of whitespace (incl. tabs/newlines) so "zelda  " and
    # "zelda" are the same search and share one cache entry.
    query = ' '.join((args.get('query') or '').split())
    if not query:
        raise ValidationError('The "query" parameter is required.')
    if len(query) > MAX_QUERY_LENGTH:
        raise ValidationError(f'The search term must be at most {MAX_QUERY_LENGTH} characters.')

    genre = (args.get('genre') or '').strip() or None
    mode = (args.get('mode') or '').strip() or None
    if genre or mode:
        filters = get_filters()
        if genre and genre not in {str(g['id']) for g in filters['genres']}:
            raise ValidationError('Unknown genre.')
        if mode and mode not in {str(m['id']) for m in filters['modes']}:
            raise ValidationError('Unknown game mode.')

    ordering = (args.get('ordering') or '').strip() or None
    if ordering and ordering not in ORDERINGS:
        raise ValidationError(f'"ordering" must be one of: {", ".join(ORDERINGS)}.')

    try:
        page = int(args.get('page') or 1)
    except ValueError:
        page = 0
    if page < 1:
        raise ValidationError('"page" must be a positive integer.')

    return query, genre, mode, ordering, page
