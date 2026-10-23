from pydantic import BaseModel
from typing import Optional


class DocumentResponse(BaseModel):
    documentId: int
    originalFilename: str
    fileSize: int
    fileType: str
    documentStatus: str
    clauseCount: Optional[int] = None
    contentPreview: Optional[str] = None
    createdAt: str = ""
