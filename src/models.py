"""
Shared Pydantic models for the AI Research Assistant.
Used by both the API and the worker.
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime
import uuid


class TaskStatus(str, Enum):
    """Status of an inference task."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class InferenceRequest(BaseModel):
    """Request model for submitting an inference task."""
    prompt: str = Field(..., min_length=1, max_length=4096, description="The prompt to send to the LLM")
    max_tokens: int = Field(default=256, ge=1, le=2048, description="Maximum tokens to generate")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    top_p: float = Field(default=0.9, ge=0.0, le=1.0, description="Top-p (nucleus) sampling")


class InferenceTask(BaseModel):
    """Internal task representation stored in Redis."""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.7
    top_p: float = 0.9
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TaskSubmitResponse(BaseModel):
    """Response when a task is submitted."""
    task_id: str
    status: TaskStatus
    message: str = "Task submitted successfully. Poll /task/{task_id} for results."


class TaskStatusResponse(BaseModel):
    """Response when checking task status."""
    task_id: str
    status: TaskStatus
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    api: str = "healthy"
    redis: str = "unknown"
    worker: str = "unknown"

