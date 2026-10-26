import json
from datetime import datetime, timedelta, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import analysis, providers

INTERVALS = (10, 25, 50)


class BadRequest(ValueError):
    pass


def _point(obj, name):
    try:
        lat, lng = float(obj["lat"]), float(obj["lng"])
    except (TypeError, KeyError, ValueError):
        raise BadRequest(f"'{name}' needs numeric lat and lng")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise BadRequest(f"'{name}' coordinates are out of range")
    return {"lat": lat, "lng": lng}


def _departure(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise BadRequest("'departure' must be an ISO 8601 date/time")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if not (now - timedelta(hours=24) <= dt <= now + timedelta(days=14)):
        raise BadRequest("Departure must be within the forecast window (from 24 hours ago to 14 days ahead)")
    return dt


@require_GET
def health(request):
    return JsonResponse({"ok": True})


@require_GET
def geocode(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 3:
        return JsonResponse({"results": []})
    try:
        return JsonResponse({"results": providers.geocode(q)})
    except providers.ProviderError as exc:
        return JsonResponse({"error": str(exc)}, status=502)


@csrf_exempt
@require_POST
def analyze(request):
    try:
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            raise BadRequest("Body must be JSON")
        origin = _point(body.get("origin") or {}, "origin")
        destination = _point(body.get("destination") or {}, "destination")
        departure = _departure(body.get("departure"))
        try:
            weight = float(body.get("weight_lb"))
        except (TypeError, ValueError):
            raise BadRequest("'weight_lb' must be a number")
        if not 0 < weight <= 150_000:
            raise BadRequest("'weight_lb' must be between 1 and 150,000")
        interval = int(body.get("interval_mi", 25))
        if interval not in INTERVALS:
            raise BadRequest("'interval_mi' must be 10, 25 or 50")
        return JsonResponse(analysis.analyze(origin, destination, departure, weight, interval))
    except BadRequest as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except providers.ProviderError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
