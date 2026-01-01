# This block is now in providers.tf
# provider "aws" {
#   region = var.aws_region
# }

# --- Unique Suffix for Naming ---
# This ensures that resource names are unique for each deployment,
# preventing collisions from failed pipeline runs.
resource "random_id" "suffix" {
  byte_length = 4
}

# --- Networking (VPC and Subnets) ---
# Using default VPC and subnets for simplicity.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Get a specific subnet for the EC2 instance (first available)
data "aws_subnet" "first" {
  id = data.aws_subnets.default.ids[0]
}

# --- ECS Cluster ---
resource "aws_ecs_cluster" "ml_app_cluster" {
  name = "${var.project_name}-cluster"
}

# --- Application Load Balancer (ALB) ---
resource "aws_lb" "ml_app_lb" {
  name               = "${var.project_name_short}-lb-${random_id.suffix.hex}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.lb_sg.id]
  subnets            = data.aws_subnets.default.ids

  tags = {
    Name = "${var.project_name}-lb"
  }
}

resource "aws_lb_target_group" "ml_app_tg" {
  name        = "${var.project_name_short}-tg-${random_id.suffix.hex}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.ml_app_lb.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ml_app_tg.arn
  }
}

# --- Security Groups ---

# Security group for the Load Balancer
resource "aws_security_group" "lb_sg" {
  name        = "${var.project_name_short}-lb-sg-${random_id.suffix.hex}"
  description = "Allow HTTP traffic to Load Balancer"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Security group for Redis
resource "aws_security_group" "redis_sg" {
  name        = "${var.project_name_short}-redis-sg-${random_id.suffix.hex}"
  description = "Allow Redis traffic from API and Worker"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    protocol    = "tcp"
    from_port   = 6379
    to_port     = 6379
    security_groups = [
      aws_security_group.ecs_tasks_sg.id,
      aws_security_group.worker_sg.id
    ]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Security group for the ECS API Tasks
resource "aws_security_group" "ecs_tasks_sg" {
  name        = "${var.project_name_short}-tasks-sg-${random_id.suffix.hex}"
  description = "Allow traffic from the Load Balancer to the ECS tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    protocol        = "tcp"
    from_port       = 8000
    to_port         = 8000
    security_groups = [aws_security_group.lb_sg.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Security group for the GPU Worker EC2
resource "aws_security_group" "worker_sg" {
  name        = "${var.project_name_short}-worker-sg-${random_id.suffix.hex}"
  description = "Security group for GPU worker instance"
  vpc_id      = data.aws_vpc.default.id

  # SSH access (optional, for debugging)
  ingress {
    protocol    = "tcp"
    from_port   = 22
    to_port     = 22
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- IAM Roles ---

# Role for ECS tasks (API)
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.project_name_short}-ecs-task-role-${random_id.suffix.hex}"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "ecs-tasks.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

# Role for ECS task execution
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${var.project_name_short}-ecs-exec-role-${random_id.suffix.hex}"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "ecs-tasks.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Role for EC2 GPU Worker
resource "aws_iam_role" "worker_role" {
  name = "${var.project_name_short}-worker-role-${random_id.suffix.hex}"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "ec2.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_instance_profile" "worker_profile" {
  name = "${var.project_name_short}-worker-profile-${random_id.suffix.hex}"
  role = aws_iam_role.worker_role.name
}

# Allow worker to pull from ECR
resource "aws_iam_role_policy_attachment" "worker_ecr_policy" {
  role       = aws_iam_role.worker_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# --- CloudWatch Log Groups ---
resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/ecs/${var.project_name}/api"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "redis_logs" {
  name              = "/ecs/${var.project_name}/redis"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "worker_logs" {
  name              = "/ec2/${var.project_name}/worker"
  retention_in_days = 7
}

# --- ElastiCache Redis (Cheapest option: t3.micro) ---
resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.project_name_short}-redis-subnet-${random_id.suffix.hex}"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project_name_short}-redis-${random_id.suffix.hex}"
  engine               = "redis"
  node_type            = "cache.t3.micro"  # Cheapest option ~$12/month
  num_cache_nodes      = 1
  port                 = 6379
  parameter_group_name = "default.redis7"
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [aws_security_group.redis_sg.id]

  tags = {
    Name = "${var.project_name}-redis"
  }
}

# --- ECS Task Definition for API ---
resource "aws_ecs_task_definition" "api_task" {
  family                   = "${var.project_name}-api-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn

  container_definitions = jsonencode([
    {
      name      = "${var.project_name}-api"
      image     = var.api_image_uri
      cpu       = var.api_cpu
      memory    = var.api_memory
      essential = true
      
      portMappings = [{
        containerPort = 8000
        hostPort      = 8000
        protocol      = "tcp"
      }]
      
      environment = [
        { name = "REDIS_HOST", value = aws_elasticache_cluster.redis.cache_nodes[0].address },
        { name = "REDIS_PORT", value = "6379" }
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api_logs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

# --- ECS Service for API ---
resource "aws_ecs_service" "api_service" {
  name            = "${var.project_name}-api-service"
  cluster         = aws_ecs_cluster.ml_app_cluster.id
  task_definition = aws_ecs_task_definition.api_task.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks_sg.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ml_app_tg.arn
    container_name   = "${var.project_name}-api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener.http,
    aws_elasticache_cluster.redis
  ]
}

# --- GPU Worker EC2 Spot Instance ---
# Using g4dn.xlarge (NVIDIA T4, 16GB VRAM) - cheapest GPU option
# Spot pricing: ~$0.15-0.20/hour vs $0.526/hour on-demand

# Get latest Deep Learning AMI with GPU support
data "aws_ami" "deep_learning" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04) *"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# EC2 Instance for GPU Worker (On-Demand since Spot limits may be hit)
resource "aws_instance" "gpu_worker" {
  count = var.deploy_gpu_worker ? 1 : 0

  ami                    = data.aws_ami.deep_learning.id
  instance_type          = var.gpu_instance_type
  
  subnet_id                   = data.aws_subnet.first.id
  vpc_security_group_ids      = [aws_security_group.worker_sg.id]
  iam_instance_profile        = aws_iam_instance_profile.worker_profile.name
  associate_public_ip_address = true
  
  # Key pair for SSH access (optional)
  key_name = var.ssh_key_name != "" ? var.ssh_key_name : null

  # Root volume - needs space for model
  root_block_device {
    volume_size = 100  # GB
    volume_type = "gp3"
  }

  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -e
    
    # Log everything
    exec > >(tee /var/log/worker-setup.log) 2>&1
    
    echo "=== Starting GPU Worker Setup ==="
    
    # Wait for GPU driver to be ready
    sleep 30
    
    # Install Docker if not present
    if ! command -v docker &> /dev/null; then
      echo "Installing Docker..."
      curl -fsSL https://get.docker.com -o get-docker.sh
      sh get-docker.sh
      usermod -aG docker ubuntu
    fi
    
    # Install NVIDIA Container Toolkit
    echo "Installing NVIDIA Container Toolkit..."
    distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
      sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
      sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update
    apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
    
    # Pull and run the worker container
    echo "Pulling worker image..."
    docker pull ${var.worker_image_uri}
    
    echo "Starting worker container..."
    docker run -d \
      --name vllm-worker \
      --gpus all \
      --restart unless-stopped \
      -e REDIS_HOST="${aws_elasticache_cluster.redis.cache_nodes[0].address}" \
      -e REDIS_PORT="6379" \
      -e MODEL_NAME="${var.model_name}" \
      -e MODEL_MAX_LENGTH="${var.model_max_length}" \
      -e GPU_MEMORY_UTILIZATION="0.85" \
      ${var.worker_image_uri}
    
    echo "=== GPU Worker Setup Complete ==="
  EOF
  )

  tags = {
    Name = "${var.project_name}-gpu-worker"
  }
}
