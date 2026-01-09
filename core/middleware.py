import uuid
from threading import local

_thread_locals = local()

def get_current_request_id():
    return getattr(_thread_locals, 'request_id', None)

class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID', uuid.uuid4().hex)
        request.request_id = request_id
        _thread_locals.request_id = request_id

        response = self.get_response(request)

        response['X-Request-ID'] = request_id
        return response
