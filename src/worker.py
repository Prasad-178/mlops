"""
vLLM Worker for processing inference tasks from Redis queue.

This worker:
1. Connects to Redis and polls for tasks
2. Loads the model using vLLM for fast inference
3. Processes tasks and stores results back in Redis
4. Sends heartbeats so the API knows the worker is alive
"""
import os
import sys
import json
import time
import signal
import logging
from datetime import datetime
from typing import Optional

import redis
from vllm import LLM, SamplingParams

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import InferenceTask, TaskStatus

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

# Model configuration
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-1.5B-Instruct")  # Small model for T4 GPU
MODEL_MAX_LENGTH = int(os.getenv("MODEL_MAX_LENGTH", "4096"))
GPU_MEMORY_UTILIZATION = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.85"))

# Redis keys (must match api.py)
TASK_QUEUE_KEY = "llm:task_queue"
TASK_DATA_PREFIX = "llm:task:"
WORKER_HEARTBEAT_KEY = "llm:worker:heartbeat"

# Worker settings
POLL_INTERVAL = 1  # seconds
HEARTBEAT_INTERVAL = 30  # seconds

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


def load_model() -> LLM:
    """Load the vLLM model."""
    logger.info(f"Loading model: {MODEL_NAME}")
    logger.info(f"Max model length: {MODEL_MAX_LENGTH}")
    logger.info(f"GPU memory utilization: {GPU_MEMORY_UTILIZATION}")
    
    try:
        llm = LLM(
            model=MODEL_NAME,
            max_model_len=MODEL_MAX_LENGTH,
            gpu_memory_utilization=GPU_MEMORY_UTILIZATION,
            trust_remote_code=True,  # Some models need this
            dtype="half",  # Use FP16 for memory efficiency on T4
            enforce_eager=True,  # Disable CUDA graph compilation (fixes T4 compatibility)
        )
        logger.info("Model loaded successfully!")
        return llm
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        raise


def connect_redis() -> redis.Redis:
    """Connect to Redis."""
    logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
    
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )
    
    # Test connection
    client.ping()
    logger.info("Connected to Redis!")
    return client


def update_heartbeat(redis_client: redis.Redis):
    """Update worker heartbeat in Redis."""
    try:
        redis_client.set(
            WORKER_HEARTBEAT_KEY,
            datetime.utcnow().isoformat(),
            ex=120  # Expire after 2 minutes
        )
    except Exception as e:
        logger.warning(f"Failed to update heartbeat: {e}")


def get_next_task(redis_client: redis.Redis) -> Optional[InferenceTask]:
    """Get the next task from the queue."""
    try:
        # BLPOP blocks until a task is available (with timeout)
        result = redis_client.blpop(TASK_QUEUE_KEY, timeout=POLL_INTERVAL)
        
        if not result:
            return None
        
        _, task_id = result
        task_key = f"{TASK_DATA_PREFIX}{task_id}"
        
        # Get task data
        task_data = redis_client.get(task_key)
        if not task_data:
            logger.warning(f"Task {task_id} not found in Redis")
            return None
        
        return InferenceTask.model_validate_json(task_data)
    except Exception as e:
        logger.error(f"Error getting task: {e}")
        return None


def update_task(redis_client: redis.Redis, task: InferenceTask):
    """Update task data in Redis."""
    try:
        task_key = f"{TASK_DATA_PREFIX}{task.task_id}"
        redis_client.set(task_key, task.model_dump_json())
    except Exception as e:
        logger.error(f"Failed to update task {task.task_id}: {e}")


def process_task(llm: LLM, task: InferenceTask) -> InferenceTask:
    """Process a single inference task."""
    logger.info(f"Processing task {task.task_id}: '{task.prompt[:50]}...'")
    
    try:
        # Format prompt for instruction-tuned model
        # Qwen2.5-Instruct uses ChatML format
        formatted_prompt = f"<|im_start|>user\n{task.prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        # Set up sampling parameters
        sampling_params = SamplingParams(
            max_tokens=task.max_tokens,
            temperature=task.temperature,
            top_p=task.top_p,
            stop=["<|im_end|>", "<|im_start|>"],  # Stop tokens for Qwen
        )
        
        # Run inference
        start_time = time.time()
        outputs = llm.generate([formatted_prompt], sampling_params)
        inference_time = time.time() - start_time
        
        # Extract result
        result_text = outputs[0].outputs[0].text.strip()
        
        logger.info(f"Task {task.task_id} completed in {inference_time:.2f}s")
        logger.info(f"Result: '{result_text[:100]}...'")
        
        task.status = TaskStatus.COMPLETED
        task.result = result_text
        task.completed_at = datetime.utcnow()
        
    except Exception as e:
        logger.error(f"Task {task.task_id} failed: {e}")
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.completed_at = datetime.utcnow()
    
    return task


def run_worker():
    """Main worker loop."""
    global shutdown_requested
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Connect to Redis
    redis_client = connect_redis()
    
    # Load model
    llm = load_model()
    
    logger.info("Worker started, waiting for tasks...")
    last_heartbeat = 0
    
    while not shutdown_requested:
        current_time = time.time()
        
        # Update heartbeat periodically
        if current_time - last_heartbeat > HEARTBEAT_INTERVAL:
            update_heartbeat(redis_client)
            last_heartbeat = current_time
        
        # Get next task
        task = get_next_task(redis_client)
        
        if task is None:
            continue
        
        # Mark task as processing
        task.status = TaskStatus.PROCESSING
        update_task(redis_client, task)
        
        # Process the task
        task = process_task(llm, task)
        
        # Update task with result
        update_task(redis_client, task)
    
    logger.info("Worker shutting down gracefully...")
    redis_client.close()


if __name__ == "__main__":
    run_worker()

