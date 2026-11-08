'''
Exceptions raised by the backend.

Every ApiError carries an HTTP status code and a message that is safe to show
to users (no credentials, no upstream response bodies). app.py turns them into
{"error": message} JSON responses.
'''


class ApiError(Exception):
    '''Base class for errors that become a JSON error response.'''

    status_code = 500

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class ValidationError(ApiError):
    '''The client sent a missing or invalid parameter.'''

    status_code = 400


class NotFoundError(ApiError):
    '''The requested game does not exist.'''

    status_code = 404


class UpstreamError(ApiError):
    '''IGDB (or Twitch) failed, timed out, or returned something unusable.'''

    status_code = 502


class TokenError(UpstreamError):
    '''Raised when an IGDB access token cannot be obtained from Twitch.'''


class PriceLookupError(Exception):
    '''
    CheapShark failed or timed out. Never sent to the client as an error:
    the game is still returned, with deals set to null and deals_error set.
    '''
