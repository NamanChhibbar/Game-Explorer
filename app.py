"""
Game Explorer - Flask backend.

Serves the single-page frontend (templates/ + static/) and will expose JSON
endpoints that proxy and merge data from IGDB and CheapShark:

    GET /                 -> index.html
    GET /api/filters      -> genres and game modes for the dropdowns
    GET /api/search       -> one page of search results
    GET /api/game/<id>    -> merged game details + store prices

Credentials are read from environment variables and never sent to the client.
"""

import os

from flask import Flask, jsonify, render_template

# Load a local .env during development. On Cloud Run the variables are set
# with --set-env-vars, so python-dotenv is optional at runtime.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IGDB_CLIENT_ID = os.environ.get("IGDB_CLIENT_ID")
IGDB_CLIENT_SECRET = os.environ.get("IGDB_CLIENT_SECRET")

if not IGDB_CLIENT_ID or not IGDB_CLIENT_SECRET:
    # Warn without printing either value.
    print("WARNING: IGDB_CLIENT_ID / IGDB_CLIENT_SECRET are not set; API calls will fail.")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handlers - always answer /api/* with JSON, never an HTML error page
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Not found."}), 404


@app.errorhandler(500)
def server_error(_error):
    return jsonify({"error": "Something went wrong on the server."}), 500


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the single-page frontend."""
    return render_template("index.html")


if __name__ == "__main__":
    # Local development server. In production gunicorn imports `app` directly.
    port = int(os.environ.get("PORT", 8080))
    app.run(host="127.0.0.1", port=port, debug=True)
