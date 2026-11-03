output "public_ip" {
  value = aws_eip.lifemap.public_ip
}

output "api_url" {
  value = "http://${aws_eip.lifemap.public_ip}/health"
}

output "jenkins_url" {
  value = "http://${aws_eip.lifemap.public_ip}:8088"
}

output "ssh" {
  value = "ssh ubuntu@${aws_eip.lifemap.public_ip}"
}
