"""JSON bodies are bounded after HTTP content decoding."""
import json
import requests

MAX_JSON_BYTES = 8 * 1024 * 1024


class NoRedirectSession(requests.Session):
    def resolve_redirects(self, *args, **kwargs):
        # Requests otherwise consumes the redirect body to prepare Response.next,
        # even with allow_redirects=False. The caller handles each hop itself.
        return iter(())


def response_json(response, limit=MAX_JSON_BYTES):
    announced = response.headers.get("Content-Length")
    if announced and int(announced) > limit:
        raise ValueError("Resposta da API excede o limite de tamanho.")
    body = bytearray()
    for chunk in response.iter_content(65536):
        if len(body) + len(chunk) > limit:
            raise ValueError("Resposta da API excede o limite de tamanho.")
        body.extend(chunk)
    return json.loads(body)
