"""Run PyBridge side-by-side with django-ninja in the same Django ASGI app.

Both frameworks use Pydantic — you can share schemas across them. The mounting
mechanism is the *Django ASGI router* (not the URL conf), because PyBridge is a
full ASGI app (with WebSockets), and Django's URLconf is HTTP-only.

Run:
    uvicorn examples.django_ninja:application
"""

from __future__ import annotations

import django
from django.conf import settings

# Configure Django BEFORE importing django-ninja (its module body reads settings).
if not settings.configured:
    settings.configure(
        DEBUG=True,
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        SECRET_KEY="dev-only-not-secret",
        INSTALLED_APPS=[],
        TEMPLATES=[{
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": False,
            "OPTIONS": {},
        }],
    )
    django.setup()

from django.core.asgi import get_asgi_application  # noqa: E402
from django.http import JsonResponse  # noqa: E402
from django.urls import path  # noqa: E402
from ninja import NinjaAPI, Schema  # noqa: E402

from examples.basic import bridge  # noqa: E402  PyBridge with all procedures


# --- django-ninja side ----------------------------------------------------

api = NinjaAPI(title="My Ninja API", version="1.0")


class HelloOut(Schema):
    message: str


@api.get("/hello", response=HelloOut)
def hello(request, name: str = "world"):
    return {"message": f"hello {name}"}


# --- plain Django view (just to prove all three coexist) -------------------

def home(request):
    return JsonResponse({"ok": True, "app": "django"})


urlpatterns = [
    path("", home),
    path("ninja/", api.urls),
]


# --- ASGI router: route /rpc/* and /ws to PyBridge, everything else to Django

django_app = get_asgi_application()
bridge_app = bridge.asgi()


async def application(scope, receive, send):
    if scope["type"] in {"http", "websocket"}:
        path = scope.get("path", "")
        if path.startswith("/rpc") or path == "/ws":
            await bridge_app(scope, receive, send)
            return
    await django_app(scope, receive, send)
