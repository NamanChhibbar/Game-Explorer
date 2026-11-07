'''
Game Explorer - Flask backend.

Serves the single-page frontend (templates/ + static/) and will expose JSON
endpoints that proxy and merge data from IGDB and CheapShark:

    GET /                 -> index.html
    GET /api/filters      -> genres and game modes for the dropdowns
    GET /api/search       -> one page of search results
    GET /api/game/<id>    -> merged game details + store prices

Configuration and upstream helpers live in the core/ package. Credentials are
read from environment variables and never sent to the client.
'''

import logging

from flask import Flask, jsonify, render_template

from core.config import IGDB_CLIENT_ID, IGDB_CLIENT_SECRET, PORT
from core.http_client import http
from core.token_store import TokenStore

# Show INFO logs from core/ (e.g. 'Obtained new IGDB access token') locally
# and in the Cloud Run log viewer.
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')

app = Flask(__name__)

# One token store for the whole process, shared by every request thread.
token_store = TokenStore(IGDB_CLIENT_ID, IGDB_CLIENT_SECRET, session=http)


# ---------------------------------------------------------------------------
# Error handlers - always answer with JSON, never an HTML error page
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    return jsonify({'error': 'Not found.'}), 404


@app.errorhandler(500)
def server_error(_error):
    return jsonify({'error': 'Something went wrong on the server.'}), 500


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    '''Serve the single-page frontend.'''
    return render_template('index.html')


if __name__ == '__main__':
    # Local development server. In production gunicorn imports `app` directly.
    app.run(host='127.0.0.1', port=PORT, debug=True)
