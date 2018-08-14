class BaseException(Exception):
    def __init__(self, what='', message=None):
        super(BaseException, self).__init__(what)
        self.message = message


class NoPrivateMessage(BaseException):
    pass


class NoHandlerFound(BaseException):
    def __init__(self, suggestion='', message=None):
        super(NoHandlerFound, self).__init__(message=message)
        self.suggestion = suggestion


class NoFollowupHandlerFound(NoHandlerFound):
    pass


class HandlerReportedIssues(BaseException):
    def __init__(self, handler_cls, handler_issues, message=None):
        super(HandlerReportedIssues, self).__init__(message=message)
        self.handler_cls = handler_cls
        self.handler_issues = handler_issues


class Cancelled(Exception):
    pass


class TryAgain(Exception):
    pass


class NotFound(Exception):
    pass


class WaitTimeout(Exception):
    def __init__(self, elapsed):
        super(WaitTimeout, self).__init__()
        self.elapsed = elapsed


class Dying(Exception):
    pass


class ConsoleNotReady(BaseException):
    pass


class Unstoppable(BaseException):
    pass


class ArgumentError(BaseException):
    pass


class NotAuthorized(BaseException):
    def __init__(self, what, message=None):
        super(NotAuthorized, self).__init__(what=what, message=message)
