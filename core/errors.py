'''Exceptions raised by the backend. Their messages are safe to show to users.'''


class TokenError(Exception):
    '''Raised when an IGDB access token cannot be obtained from Twitch.'''
