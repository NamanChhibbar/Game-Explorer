'''
Configuration for Game Explorer.

Credentials come only from environment variables: a local .env file during
development, --set-env-vars on Cloud Run. Never hardcode them here.
'''

import os
import logging

logger = logging.getLogger(__name__)

# Load a local .env during development. On Cloud Run the variables are set
# with --set-env-vars, so python-dotenv is optional at runtime.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    logger.info('python-dotenv not installed; skipping .env load')

# --- Credentials -----------------------------------------------------------
IGDB_CLIENT_ID = os.environ.get('IGDB_CLIENT_ID')
IGDB_CLIENT_SECRET = os.environ.get('IGDB_CLIENT_SECRET')

if not IGDB_CLIENT_ID or not IGDB_CLIENT_SECRET:
    # Warn without printing either value.
    logger.warning('IGDB_CLIENT_ID / IGDB_CLIENT_SECRET are not set; API calls will fail.')

# --- Twitch token ----------------------------------------------------------
TWITCH_TOKEN_URL = 'https://id.twitch.tv/oauth2/token'
TOKEN_REFRESH_MARGIN = 300  # renew 5 minutes before the token expires
TOKEN_TIMEOUT = 10          # seconds to wait for Twitch

# --- IGDB ------------------------------------------------------------------
IGDB_BASE_URL = 'https://api.igdb.com/v4'
IGDB_IMAGE_URL = 'https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg'
IGDB_TIMEOUT = 10              # seconds per IGDB request
IGDB_MAX_REQUESTS_PER_SECOND = 4  # IGDB's documented limit per set of credentials
IGDB_RATE_LIMIT_RETRY_DELAY = 1.0  # if IGDB still answers 429, wait this long before one retry

# IGDB game_type ids included in search results: Main Game (0), Expansion (2),
# Standalone Expansion (4), Remake (8), Remaster (9). This leaves out DLC,
# bundles, mods, episodes, seasons, "Expanded Game" re-releases, ports,
# forks, packs and updates, which otherwise crowd the sorted results.
IGDB_GAME_TYPES = (0, 2, 4, 8, 9)

# --- CheapShark ------------------------------------------------------------
CHEAPSHARK_BASE_URL = 'https://www.cheapshark.com/api/1.0'
CHEAPSHARK_SITE_URL = 'https://www.cheapshark.com'  # store icon paths are relative to this
CHEAPSHARK_TIMEOUT = 5         # seconds per CheapShark request

# CheapShark rejects requests without a descriptive User-Agent (the default
# python-requests one gets HTTP 400). Override with APP_USER_AGENT, e.g. to
# add a contact email.
USER_AGENT = os.environ.get('APP_USER_AGENT', 'GameExplorer/1.0 (CSCI 571 student project)')

# --- Cache -----------------------------------------------------------------
CACHE_MAX_ENTRIES = 500
SEARCH_TTL = 15 * 60           # search pages
GAME_TTL = 15 * 60             # game detail responses
FILTERS_TTL = 24 * 60 * 60     # genre and game mode lists
STORES_TTL = 24 * 60 * 60      # CheapShark store list

# --- Search ----------------------------------------------------------------
PAGE_SIZE = 12
MAX_GAME_ID = 2**31 - 1  # IGDB ids are 32-bit; larger values make IGDB return 400
MAX_QUERY_LENGTH = 100
ORDERINGS = ('rating', 'critics', 'newest', 'name')

# --- Local server ----------------------------------------------------------
PORT = int(os.environ.get('PORT', 8080))
