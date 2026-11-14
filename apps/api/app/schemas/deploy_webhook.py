from pydantic import BaseModel


class RotateWebhookSecretResponse(BaseModel):
    secret: str
