from __future__ import annotations

from mangum import Mangum

from server.main import app


# Lambda receives API Gateway or Function URL events and adapts them to ASGI.
handler = Mangum(app, lifespan='off')