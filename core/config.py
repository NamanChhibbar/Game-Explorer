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

# --- Local server ----------------------------------------------------------
PORT = int(os.environ.get('PORT', 8080))
