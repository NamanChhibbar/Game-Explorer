'''Shared HTTP session for all upstream calls (Twitch, IGDB, CheapShark).'''

import requests

# One session reuses TCP/TLS connections across requests. requests.Session
# is safe to share between threads for this kind of simple usage.
http = requests.Session()
