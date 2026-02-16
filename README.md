# FastInfer

A GPU-powered LLM inference API using **vLLM** with an asynchronous task queue (**Redis**) for scalable, production-ready AI chat.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│   FastAPI   │────▶│    Redis    │────▶│ vLLM Worker │
│  (Chat UI)  │     │   (API)     │     │   (Queue)   │     │   (GPU)     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

- **FastAPI**: Serves the chat UI and REST API
- **Redis**: Task queue for async inference processing
- **vLLM Worker**: GPU inference with continuous batching (default model: Qwen3-1.7B)

## Prerequisites

- **Docker** installed and running
- (Optional) NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) for local GPU inference

## Local Development

### Start API + Redis (No GPU)

```bash
docker-compose up -d

# View logs
docker-compose logs -f api

# Access at http://localhost:8000
```

### Start with GPU Worker

```bash
docker-compose --profile gpu up -d
```

### Stop

```bash
docker-compose down
```

## API Usage

```bash
# Health check
curl http://localhost:8000/health

# Submit inference task
curl -X POST "http://localhost:8000/infer" \
     -H "Content-Type: application/json" \
     -d '{"prompt": "What is machine learning?", "max_tokens": 100}'

# Check task status (use task_id from above response)
curl "http://localhost:8000/task/<task_id>"
```

## AWS Deployment (Optional)

Infrastructure is defined in `terraform/` using Terraform. To deploy:

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

See `terraform/terraform.tfvars` to configure images, GPU worker toggle, and model settings.

To tear down:

```bash
terraform destroy
```

### CI/CD

The GitHub Actions workflow (`.github/workflows/aws.yml`) builds and pushes Docker images to ECR and runs `terraform apply` on push to `main`. It only triggers when relevant source files change (Python, Dockerfiles, Terraform, workflow configs) -- not on doc-only changes.

## Project Structure

```
fastinfer/
├── src/
│   ├── api.py              # FastAPI server (task submission, polling)
│   ├── worker.py           # vLLM worker (processes tasks from Redis)
│   └── models.py           # Shared Pydantic models
├── frontend/
│   └── index.html          # Chat UI
├── terraform/              # AWS infrastructure (ECS, EC2 GPU, Redis, ALB)
├── .github/workflows/
│   └── aws.yml             # CI/CD pipeline
├── Dockerfile.api          # API container
├── Dockerfile.worker       # GPU worker container (vLLM)
├── docker-compose.yml      # Local development
└── pyproject.toml          # Python dependencies
```

## Environment Variables

### API Service
| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_HOST` | Redis hostname | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password (optional) | None |

### Worker Service
| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_HOST` | Redis hostname | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `MODEL_NAME` | HuggingFace model ID | `Qwen/Qwen3-1.7B` |
| `MODEL_MAX_LENGTH` | Max sequence length | `4096` |
| `GPU_MEMORY_UTILIZATION` | GPU memory fraction (0-1) | `0.85` |

## License

MIT
