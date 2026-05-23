"""Expose PyBridge from a Django project.

This file is a minimal, self-contained Django ASGI setup. In a real project,
drop ``django_view(bridge)`` into your existing ``urls.py``:

    from django.urls import path
    from pybridge.integrations import django_view
    from myapp.bridge import bridge

    urlpatterns = [
        path("", django_view(bridge)),
    ]

Run this example with:
    pip install django asgiref uvicorn
    uvicorn examples.django_mount:application
"""

from __future__ import annotations

import django
from django.conf import settings
from django.urls import path

from examples.basic import bridge
from pybridge.integrations import django_view


if not settings.configured:
    settings.configure(
        DEBUG=True,
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        SECRET_KEY="dev-only-not-secret",
        INSTALLED_APPS=[],
    )
    django.setup()


urlpatterns = [
    path("", django_view(bridge)),
]


from django.core.asgi import get_asgi_application  # noqa: E402

application = get_asgi_application()
