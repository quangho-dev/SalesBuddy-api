from enum import Enum

from pydantic import BaseModel, Field


class QueryVariations(BaseModel):
    queries: list[str] = Field(default_factory=list)


class ProcessingStatus(str, Enum):
    PROCESSING = "processing"
    PARTITIONING = "partitioning"
    CHUNKING = "chunking"
    SUMMARISING = "summarising"
    VECTORIZATION = "vectorization"
    COMPLETED = "completed"
    FAILED = "failed"
