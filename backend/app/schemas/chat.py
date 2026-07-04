from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=8000)
