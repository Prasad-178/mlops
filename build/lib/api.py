"""
FastAPI Application for LLM Inference with Async Redis Queue.

This API accepts inference requests and returns a task ID immediately.
A separate worker process picks up tasks from Redis and processes them with vLLM.
Users can poll for results or (future) receive WebSocket updates.
"""
import os
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.models import (
    InferenceRequest,
    InferenceTask,
    TaskSubmitResponse,
    TaskStatusResponse,
    TaskStatus,
    HealthResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Configuration ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Redis keys
TASK_QUEUE_KEY = "llm:task_queue"  # List for pending tasks (FIFO queue)
TASK_DATA_PREFIX = "llm:task:"      # Hash for task data (task_id -> task JSON)
WORKER_HEARTBEAT_KEY = "llm:worker:heartbeat"  # Worker heartbeat timestamp

# --- Global Redis client ---
redis_client: redis.Redis = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - connect/disconnect Redis."""
    global redis_client
    
    logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
    try:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
        # Test connection
        await redis_client.ping()
        logger.info("Successfully connected to Redis!")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise RuntimeError(f"Redis connection failed: {e}")
    
    yield  # Application runs
    
    # Cleanup
    logger.info("Closing Redis connection...")
    if redis_client:
        await redis_client.close()
    logger.info("Redis connection closed.")


# --- FastAPI App ---
app = FastAPI(
    title="AI Research Assistant API",
    description="Async LLM Inference API with Redis queue and vLLM backend",
    version="0.2.0",
    lifespan=lifespan,
)

# Serve static files (frontend)
STATIC_DIR = Path(__file__).parent.parent / "frontend"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- API Endpoints ---

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    """Serve the chat frontend."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "AI Research Assistant API is running. POST to /infer to submit tasks."}


@app.post("/infer", response_model=TaskSubmitResponse)
async def submit_inference(request: InferenceRequest):
    """
    Submit an inference task to the queue.
    Returns immediately with a task ID that can be used to poll for results.
    """
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    
    # Create task
    task = InferenceTask(
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
    )
    
    logger.info(f"Submitting task {task.task_id}: '{request.prompt[:50]}...'")
    
    try:
        # Store task data in Redis
        task_key = f"{TASK_DATA_PREFIX}{task.task_id}"
        await redis_client.set(task_key, task.model_dump_json())
        
        # Add task ID to the queue
        await redis_client.rpush(TASK_QUEUE_KEY, task.task_id)
        
        logger.info(f"Task {task.task_id} queued successfully")
        
        return TaskSubmitResponse(
            task_id=task.task_id,
            status=TaskStatus.PENDING,
        )
    except Exception as e:
        logger.error(f"Failed to queue task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to queue task: {str(e)}")


@app.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Get the status and result of a task.
    Poll this endpoint to check if your inference is complete.
    """
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    
    task_key = f"{TASK_DATA_PREFIX}{task_id}"
    
    try:
        task_data = await redis_client.get(task_key)
        
        if not task_data:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        task = InferenceTask.model_validate_json(task_data)
        
        return TaskStatusResponse(
            task_id=task.task_id,
            status=task.status,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            completed_at=task.completed_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.
    Reports status of API, Redis connection, and worker.
    """
    response = HealthResponse(status="healthy", api="healthy")
    
    # Check Redis
    if redis_client:
        try:
            await redis_client.ping()
            response.redis = "healthy"
        except Exception:
            response.redis = "unhealthy"
            response.status = "degraded"
    else:
        response.redis = "not_connected"
        response.status = "degraded"
    
    # Check worker heartbeat (worker should update this every 30 seconds)
    if redis_client:
        try:
            heartbeat = await redis_client.get(WORKER_HEARTBEAT_KEY)
            if heartbeat:
                last_heartbeat = datetime.fromisoformat(heartbeat)
                age = (datetime.utcnow() - last_heartbeat).total_seconds()
                if age < 60:  # Worker heartbeat within last minute
                    response.worker = "healthy"
                else:
                    response.worker = f"stale ({int(age)}s ago)"
                    response.status = "degraded"
            else:
                response.worker = "no_heartbeat"
        except Exception:
            response.worker = "unknown"
    
    return response


@app.get("/queue/stats")
async def queue_stats():
    """Get queue statistics."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    
    try:
        queue_length = await redis_client.llen(TASK_QUEUE_KEY)
        return {
            "pending_tasks": queue_length,
        }
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# For local development
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
