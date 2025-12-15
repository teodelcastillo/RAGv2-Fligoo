from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/document/', include('apps.document.api.urls')),
    path('api/chat/', include('apps.chat.api.urls')),
    path('api/projects/', include('apps.project.api.urls')),
    path('api/evaluations/', include('apps.evaluation.api.urls')),
    path('api/auth/', include('apps.authentication.api.urls')),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
