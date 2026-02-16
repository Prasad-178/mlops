# FastInfer

A GPU-powered LLM inference API using **vLLM** with an asynchronous task queue (**Redis**) for scalable, production-ready AI chat.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│  FastAPI    │────▶│   Redis     │────▶│ vLLM Worker │
│   (Chat UI) │     │  (ECS)      │     │(ElastiCache)│     │ (EC2 GPU)   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

- **FastAPI** (ECS Fargate): Serves the chat UI and REST API
- **Redis** (ElastiCache): Task queue for async processing
- **vLLM Worker** (EC2 g4dn.xlarge): GPU inference with Qwen3-1.7B

## Prerequisites

1. **AWS CLI** configured with credentials
2. **Terraform** installed
3. **Docker** installed and running
4. **AWS ECR Public Repository** created (one-time setup)

---

## 🚀 Complete Deployment Guide

### Step 1: Create ECR Repository (First Time Only)

```bash
# Create a public ECR repository
aws ecr-public create-repository \
  --repository-name prasadjs178/mlops-project \
  --region us-east-1
```

### Step 2: Authenticate Docker with ECR

```bash
# Login to ECR Public
aws ecr-public get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin public.ecr.aws
```

### Step 3: Build and Push Docker Images

```bash
# Navigate to project root
cd /Users/prasad/Prasad/ML/projects/ai-research-assistant

# Build and push API image (for ECS Fargate)
docker buildx build --platform linux/amd64 \
  -f Dockerfile.api \
  -t public.ecr.aws/x5h9x8z0/prasadjs178/mlops-project:api-latest \
  --push .

# Build and push Worker image (for EC2 GPU)
docker buildx build --platform linux/amd64 \
  -f Dockerfile.worker \
  -t public.ecr.aws/x5h9x8z0/prasadjs178/mlops-project:worker-latest \
  --push .
```

> ⏱️ **Note**: Worker image build takes ~10-15 minutes (large PyTorch/vLLM dependencies)

### Step 4: Deploy Infrastructure with Terraform

```bash
# Navigate to terraform directory
cd terraform

# Initialize Terraform (first time or after changes)
terraform init

# Preview what will be created
terraform plan

# Deploy everything
terraform apply -auto-approve
```

### Step 5: Enable GPU Worker (Optional - Costs ~$0.53/hour)

By default, the GPU worker is disabled to save costs. To enable it:

```bash
# Edit terraform.tfvars
# Change: deploy_gpu_worker = false
# To:     deploy_gpu_worker = true

# Then apply
terraform apply -auto-approve
```

### Step 6: Get Your App URL

```bash
terraform output app_url
```

Open the URL in your browser to access the chat UI!

---

## 🗑️ Complete Destruction Guide

### Option A: Destroy Everything (Recommended)

```bash
cd terraform
terraform destroy -auto-approve
```

This removes:
- EC2 GPU instance
- ECS cluster and services
- Load Balancer
- ElastiCache Redis
- Security groups
- IAM roles
- CloudWatch logs

### Option B: Just Stop the GPU Worker (Save Costs)

```bash
# Edit terraform.tfvars
# Change: deploy_gpu_worker = true
# To:     deploy_gpu_worker = false

cd terraform
terraform apply -auto-approve
```

### Option C: Delete ECR Images Too

```bash
# Delete all images in the repository
aws ecr-public batch-delete-image \
  --repository-name prasadjs178/mlops-project \
  --region us-east-1 \
  --image-ids imageTag=api-latest imageTag=worker-latest

# Or delete the entire repository
aws ecr-public delete-repository \
  --repository-name prasadjs178/mlops-project \
  --region us-east-1 \
  --force
```

---

## 🖥️ Local Development

### Run API + Redis Locally (No GPU)

```bash
# Start Docker Desktop first
open -a Docker

# Run API and Redis
docker-compose up -d

# View logs
docker-compose logs -f api

# Access at http://localhost:8000
```

### Stop Local Services

```bash
docker-compose down
```

---

## 📋 Quick Reference Commands

### Deployment (Full)

```bash
# 1. Login to ECR
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws

# 2. Build & Push Images
cd /Users/prasad/Prasad/ML/projects/ai-research-assistant
docker buildx build --platform linux/amd64 -f Dockerfile.api -t public.ecr.aws/x5h9x8z0/prasadjs178/mlops-project:api-latest --push .
docker buildx build --platform linux/amd64 -f Dockerfile.worker -t public.ecr.aws/x5h9x8z0/prasadjs178/mlops-project:worker-latest --push .

# 3. Deploy Infrastructure
cd terraform
terraform init
terraform apply -auto-approve

# 4. Get URL
terraform output app_url
```

### Destruction (Full)

```bash
# 1. Destroy all AWS infrastructure
cd /Users/prasad/Prasad/ML/projects/ai-research-assistant/terraform
terraform destroy -auto-approve

# 2. (Optional) Delete ECR images
aws ecr-public batch-delete-image \
  --repository-name prasadjs178/mlops-project \
  --region us-east-1 \
  --image-ids imageTag=api-latest imageTag=worker-latest
```

### Check Status

```bash
# Get app URL
cd terraform && terraform output app_url

# Check health
curl "$(terraform output -raw app_url)/health"

# Check GPU worker logs (if running)
INSTANCE_ID=$(terraform output -raw gpu_worker_instance_id)
aws ssm send-command \
  --instance-ids $INSTANCE_ID \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker logs vllm-worker 2>&1 | tail -30"]' \
  --query "Command.CommandId" --output text
```

---

## 💰 Cost Breakdown

| Resource | Cost | Notes |
|----------|------|-------|
| ECS Fargate (API) | ~$0.01/hour | 0.25 vCPU, 512MB |
| ElastiCache Redis | ~$0.02/hour | cache.t3.micro |
| EC2 g4dn.xlarge | ~$0.53/hour | GPU worker (when enabled) |
| Load Balancer | ~$0.02/hour | Application LB |

**Tip**: Disable the GPU worker when not testing to save ~$0.53/hour!

---

## 🔧 Troubleshooting

### Docker Build Fails
```bash
# Ensure Docker Desktop is running
open -a Docker
# Wait 30 seconds, then retry
```

### ECR Push Fails (403 Forbidden)
```bash
# Re-authenticate
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws
```

### GPU Worker Not Starting
```bash
# Check if you have GPU quota (need 4 vCPUs for g4dn.xlarge)
aws service-quotas get-service-quota \
  --service-code ec2 \
  --quota-code L-DB2E81BA \
  --query "Quota.Value"
# Should return 4 or higher
```

### Model Not Loading
```bash
# Check worker logs via SSM
INSTANCE_ID=$(cd terraform && terraform output -raw gpu_worker_instance_id)
aws ssm send-command \
  --instance-ids $INSTANCE_ID \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker logs vllm-worker 2>&1 | tail -50"]' \
  --output text
```

---

## 📁 Project Structure

```
ai-research-assistant/
├── src/
│   ├── api.py          # FastAPI endpoints
│   ├── worker.py       # vLLM GPU worker
│   └── models.py       # Pydantic models
├── frontend/
│   └── index.html      # Chat UI
├── terraform/
│   ├── main.tf         # AWS infrastructure
│   ├── variables.tf    # Configuration variables
│   ├── outputs.tf      # Output values
│   └── terraform.tfvars # Your settings
├── Dockerfile.api      # API container
├── Dockerfile.worker   # GPU worker container
├── docker-compose.yml  # Local development
└── README.md           # This file
```

---

## License

MIT

