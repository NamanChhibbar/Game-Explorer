'''
Game Explorer - Flask backend.

Serves the single-page frontend (templates/ + static/) and JSON endpoints that
proxy and merge data from IGDB and CheapShark:

    GET /                 -> index.html
    GET /api/filters      -> genres and game modes for the dropdowns
    GET /api/search       -> one page of search results
    GET /api/game/<id>    -> merged game details + store prices

Configuration and upstream helpers live in the core/ package. Credentials are
read from environment variables and never sent to the client.
'''

import logging

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from core.cache import TTLCache
from core.cheapshark import CheapSharkClient
from core.config import IGDB_CLIENT_ID, IGDB_CLIENT_SECRET, PORT
from core.errors import ApiError
from core.http_client import http
from core.igdb import IGDBClient
from core.services import GameExplorerService
from core.token_store import TokenStore
from core.validation import parse_search_args

# Show INFO logs from core/ (e.g. 'Obtained new IGDB access token') locally
# and in the Cloud Run log viewer.
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')

app = Flask(__name__)

# One instance of each for the whole process, shared by every request thread
# (gunicorn runs 1 worker with 8 threads, so they all see the same token and cache).
token_store = TokenStore(IGDB_CLIENT_ID, IGDB_CLIENT_SECRET, session=http)
igdb = IGDBClient(IGDB_CLIENT_ID, token_store, session=http)
cheapshark = CheapSharkClient(session=http)
service = GameExplorerService(igdb, cheapshark, cache=TTLCache())


# ---------------------------------------------------------------------------
# Error handlers - always answer with JSON, never an HTML error page
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def api_error(error: ApiError) -> tuple[Response, int]:
    '''Validation (400), not found (404) and upstream (502) errors.'''
    return jsonify({'error': error.message}), error.status_code


@app.errorhandler(404)
def not_found(_error: HTTPException) -> tuple[Response, int]:
    '''Unknown URL, including a non-numeric /api/game/<id>.'''
    return jsonify({'error': 'Not found.'}), 404


@app.errorhandler(405)
def method_not_allowed(_error: HTTPException) -> tuple[Response, int]:
    '''A known URL called with the wrong HTTP method.'''
    return jsonify({'error': 'Method not allowed.'}), 405


@app.errorhandler(500)
def server_error(_error: Exception) -> tuple[Response, int]:
    '''Any unhandled exception. The details stay in the log, not the response.'''
    return jsonify({'error': 'Something went wrong on the server.'}), 500


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index() -> str:
    '''Serve the single-page frontend.'''
    return render_template('index.html')


@app.get('/api/filters')
def api_filters() -> Response:
    '''Genres and game modes for the dropdowns.'''
    return jsonify(service.filters())


@app.get('/api/search')
def api_search() -> Response:
    '''Search IGDB. Params: query (required), genre, mode, ordering, page.'''
    query, genre, mode, ordering, page = parse_search_args(request.args, service.filters)
    return jsonify(service.search(query, genre, mode, ordering, page))


@app.get('/api/game/<int:game_id>')
def api_game(game_id: int) -> Response:
    '''Merged game details, screenshots and store prices.'''
    return jsonify(service.game(game_id))


if __name__ == '__main__':
    # Local development server. In production gunicorn imports `app` directly.
    app.run(host='127.0.0.1', port=PORT, debug=True)
