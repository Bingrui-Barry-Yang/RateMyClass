class NotFoundError(LookupError):
    """A department, course, professor or term the request names does not exist.
    The app turns it into a 404 whose detail is the message."""
