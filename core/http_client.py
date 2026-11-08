'''Shared HTTP session for all upstream calls (Twitch, IGDB, CheapShark).'''

import requests

from .config import USER_AGENT

# One session reuses TCP/TLS connections across requests. requests.Session
# is safe to share between threads for this kind of simple usage.
http = requests.Session()

# Identify the app on every outgoing request. CheapShark requires this.
http.headers['User-Agent'] = USER_AGENT
