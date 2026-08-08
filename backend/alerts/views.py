import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import AlertLog


@csrf_exempt
@require_POST
def create_log(request):
    """폰 릴레이 앱이 알림 1건을 POST하는 엔드포인트.

    기대 JSON: {"class": "siren", "direction": 90, "danger": 3, "timestamp": 1723090000000}
    """
    try:
        data = json.loads(request.body)
        log = AlertLog.objects.create(
            sound_class=data["class"],
            direction=int(data["direction"]),
            danger=int(data["danger"]),
            timestamp=int(data["timestamp"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return HttpResponseBadRequest(f"bad request: {e}")
    return JsonResponse({"status": "ok", "id": log.id})


@require_GET
def list_logs_json(request):
    """최근 로그를 JSON으로 반환 (기본 50건)"""
    limit = int(request.GET.get("limit", 50))
    logs = AlertLog.objects.all()[:limit]
    return JsonResponse(
        {
            "count": AlertLog.objects.count(),
            "logs": [
                {
                    "id": l.id,
                    "class": l.sound_class,
                    "direction": l.direction,
                    "danger": l.danger,
                    "timestamp": l.timestamp,
                    "received_at": l.received_at.isoformat(),
                }
                for l in logs
            ],
        }
    )


@require_GET
def dashboard(request):
    """심사/데모용 간단 대시보드 — 최근 50건 표"""
    logs = AlertLog.objects.all()[:50]
    return render(
        request,
        "alerts/dashboard.html",
        {"logs": logs, "total": AlertLog.objects.count()},
    )
