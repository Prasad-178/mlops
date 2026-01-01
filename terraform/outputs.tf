output "app_url" {
  description = "The public URL of the deployed API."
  value       = "http://${aws_lb.ml_app_lb.dns_name}"
}

output "redis_endpoint" {
  description = "The Redis endpoint for debugging."
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "gpu_worker_public_ip" {
  description = "The public IP of the GPU worker (if deployed)."
  value       = var.deploy_gpu_worker ? aws_instance.gpu_worker[0].public_ip : "not_deployed"
}

output "gpu_worker_instance_id" {
  description = "The EC2 Instance ID (if deployed)."
  value       = var.deploy_gpu_worker ? aws_instance.gpu_worker[0].id : "not_deployed"
}
