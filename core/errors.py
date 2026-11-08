'''
Exceptions raised by the backend.

Every ApiError carries an HTTP status code and a message that is safe to show
to users (no credentials, no upstream response bodies). app.py turns them into
{"error": message} JSON responses.
'''


class ApiError(Exception):
    '''
    Base class for errors that become a JSON error response.

    Attributes:
        status_code: HTTP status sent to the client. Subclasses override it.
        message: User-facing text sent as {"error": message}.
    '''

    status_code: int = 500

    def __init__(self, message: str) -> None:
        '''
        Args:
            message: User-facing text. Must never contain credentials or
                upstream response bodies.
        '''
        super().__init__(message)
        self.message = message


class ValidationError(ApiError):
    '''The client sent a missing or invalid parameter (HTTP 400).'''

    status_code = 400


class NotFoundError(ApiError):
    '''The requested game does not exist (HTTP 404).'''

    status_code = 404


class UpstreamError(ApiError):
    '''IGDB (or Twitch) failed, timed out, or returned something unusable (HTTP 502).'''

    status_code = 502


class TokenError(UpstreamError):
    '''An IGDB access token could not be obtained from Twitch (HTTP 502).'''


class PriceLookupError(Exception):
    '''
    CheapShark failed or timed out. Never sent to the client as an error:
    the game is still returned, with deals set to null and deals_error set.
    '''
