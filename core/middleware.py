import threading

from django.shortcuts import redirect
from django.urls import reverse

_local = threading.local()


def get_current_user():
    return getattr(_local, "user", None)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.user = getattr(request, "user", None)
        try:
            return self.get_response(request)
        finally:
            _local.user = None


class LoginRequiredMiddleware:
    OPEN_PREFIXES = ("/accounts/login", "/static/", "/admin/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(self.OPEN_PREFIXES):
            return redirect(f"{reverse('login')}?next={request.path}")
        return self.get_response(request)
