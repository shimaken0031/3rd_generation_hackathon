from django.contrib import admin
from django.urls import path, include
from django.conf import settings # MEDIA_ROOT/MEDIA_URLのために追加
from django.conf.urls.static import static # MEDIA_ROOT/MEDIA_URLのために追加
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('summarizer_app.urls')),
]