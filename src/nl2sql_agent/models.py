from pydantic import BaseModel


class UserMessage(BaseModel):
    message: str
    user_id: str
    thread_id: str
    connection_id: str | None = None
