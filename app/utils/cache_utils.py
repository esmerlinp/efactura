import hashlib
from functools import wraps
from flask import request, jsonify, Response


def http_cache(timeout=60, private=True):
    """Decorador que agrega ETag y Cache-Control a respuestas GET.

    El ETag se genera a partir del contenido de la respuesta.
    Si el cliente envía If-None-Match y coincide, se retorna 304.

    Args:
        timeout: TTL en segundos para Cache-Control max-age.
        private: Si True, la respuesta es específica del usuario.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            response = f(*args, **kwargs)

            status_code = 200
            headers = {}

            if isinstance(response, tuple):
                if len(response) == 2:
                    body, status_code = response
                elif len(response) == 3:
                    body, status_code, headers = response
                else:
                    body = response[0]
                if not isinstance(body, Response):
                    resp = jsonify(body) if not isinstance(body, (str, bytes)) else Response(body)
                else:
                    resp = body
                resp.status_code = status_code
                for k, v in headers.items():
                    resp.headers[k] = v
            elif isinstance(response, Response):
                resp = response
            else:
                resp = jsonify(response)

            content = resp.get_data()
            etag = hashlib.md5(content).hexdigest()

            cache_type = 'private' if private else 'public'
            resp.headers['ETag'] = f'"{etag}"'
            resp.headers['Cache-Control'] = f'{cache_type}, max-age={timeout}'

            if request.if_none_match and etag in request.if_none_match:
                resp.make_conditional(request)
                return resp

            return resp
        return decorated
    return decorator
