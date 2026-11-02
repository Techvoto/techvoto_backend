import logging
import time
import uuid

logger = logging.getLogger('techvoto.request')


class RequestObservabilityMiddleware:
    """Attach a correlation ID and log request timing without logging query strings or bodies."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        request.request_id = request_id
        started = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            logger.exception('request_failed request_id=%s method=%s path=%s', request_id, request.method, request.path)
            raise
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        response['X-Request-ID'] = request_id
        logger.info('request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s',
                    request_id, request.method, request.path, response.status_code, elapsed_ms)
        return response
