variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "The name of the project, used for naming resources."
  type        = string
  default     = "ai-research-assistant"
}

variable "project_name_short" {
  description = "A short name for the project (for resources with name limits)."
  type        = string
  default     = "ara"
}

# --- API Configuration ---
variable "api_image_uri" {
  description = "The Docker image URI for the FastAPI server."
  type        = string
}

variable "api_cpu" {
  description = "CPU units for the API task (1024 = 1 vCPU)."
  type        = number
  default     = 512  # 0.5 vCPU - sufficient for API
}

variable "api_memory" {
  description = "Memory for the API task in MiB."
  type        = number
  default     = 1024  # 1GB - sufficient for API
}

# --- Worker Configuration ---
variable "deploy_gpu_worker" {
  description = "Whether to deploy the GPU worker EC2 instance. Set to false to save costs when not needed."
  type        = bool
  default     = true
}

variable "worker_image_uri" {
  description = "The Docker image URI for the vLLM worker."
  type        = string
  default     = ""  # Optional, only needed if deploy_gpu_worker is true
}

variable "gpu_instance_type" {
  description = "EC2 instance type for GPU worker. g4dn.xlarge is cheapest with NVIDIA T4."
  type        = string
  default     = "g4dn.xlarge"  # NVIDIA T4 16GB, ~$0.15/hr spot
}

variable "ssh_key_name" {
  description = "Name of the SSH key pair for accessing the GPU worker (optional)."
  type        = string
  default     = ""
}

# --- Model Configuration ---
variable "model_name" {
  description = "Hugging Face model name for vLLM."
  type        = string
  default     = "Qwen/Qwen3-1.7B"
}

variable "model_max_length" {
  description = "Maximum sequence length for the model."
  type        = number
  default     = 4096
}
