from pydantic import BaseModel


class Citation(BaseModel):
    doc_id: int
    filename: str
    page_num: int | None
    chunk_id: int
    score: float
