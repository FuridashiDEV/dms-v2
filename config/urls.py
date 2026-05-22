from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

from dms.health import health_check
from dms.views import CustomLoginView, logout_view


def accounts_login_redirect(request):
    return redirect("/login/")


urlpatterns = [
    # перехват стандартного пути Django
    path("accounts/login/", accounts_login_redirect),

    path("admin/", admin.site.urls),
    path("health/", health_check, name="health_check"),

    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),

    path("", include("dms.urls", namespace="dms")),
]


from django.conf import settings
from django.conf.urls.static import static

urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT
)
