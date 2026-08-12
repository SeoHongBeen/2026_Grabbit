from django.contrib import admin
from django.urls import path

from alerts import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("logs", views.create_log),        # POST — 폰이 쏘는 곳
    path("logs.json", views.list_logs_json),  # GET — JSON 조회
    path("", views.dashboard),             # GET — 데모용 대시보드
]
