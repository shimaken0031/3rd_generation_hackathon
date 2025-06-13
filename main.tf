##############################
# プロバイダ設定
##############################
provider "aws" {
  region = var.region
}

##############################
# セキュリティグループ設定
#  - EC2 用: SSH(22), HTTP(80), HTTPS(443) を全開放
#  - RDS 用: MySQL(3306) を全開放 （今回は簡易のため0.0.0.0/0で許可）
##############################

# EC2 用セキュリティグループ
resource "aws_security_group" "app_sg" {
  name        = "hackathon-app-sg"
  description = "Allow SSH, HTTP, HTTPS"
  vpc_id      = aws_vpc.vpc.id

  # SSH 許可 (0.0.0.0/0 → 開発・無料枠用のため全開放)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTP 許可
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS 許可
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # 全アウトバウンドを許可
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # 8000 ポートを開放
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = {
    Name = "hackathon-app-sg"
  }
}

# RDS(MySQL)用セキュリティグループ
resource "aws_security_group" "db_sg" {
  name        = "hackathon-db-sg"
  description = "Allow MySQL from app servers only"
  vpc_id      = aws_vpc.vpc.id

  ingress {
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.app_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "hackathon-db-sg"
  }
}

##############################
# EC2 インスタンス作成（Docker用）
##############################
resource "aws_instance" "app_server" {
  ami                    = var.ami
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public_subnet_1a.id
  vpc_security_group_ids = [aws_security_group.app_sg.id]

  user_data = file("user_data.sh")

  tags = {
    Name = "hackathon-app-server"
  }
  depends_on = [aws_subnet.public_subnet_1a]
}

##############################
# RDS(MySQL) サブネットグループ
##############################
resource "aws_db_subnet_group" "default" {
  name       = "hackathon-db-subnet-group-v2"
  subnet_ids = [
    aws_subnet.private_subnet_1a.id,
    aws_subnet.private_subnet_1c.id
  ]
  tags = {
    Name = "hackathon-db-subnet-group"
  }
  lifecycle {
    create_before_destroy = true
  }
}

##############################
# RDS(MySQL) インスタンス作成
#  ※無料枠を想定 → db.t2.micro, ストレージ 20GB (最低値)
##############################
resource "aws_db_instance" "default" {
  identifier             = "hackathon-mysql-db"
  allocated_storage      = 20
  engine                 = "mysql"
  engine_version         = "8.0"
  instance_class         = "db.t3.micro"
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  parameter_group_name   = "default.mysql8.0"
  db_subnet_group_name   = aws_db_subnet_group.default.name
  vpc_security_group_ids = [aws_security_group.db_sg.id]
  skip_final_snapshot    = true
  publicly_accessible    = false
  multi_az               = false

  tags = {
    Name = "hackathon-mysql-db"
  }
}

##############################
# Elastic IP (EIP) の確保と関連付け
##############################

# 1) EIP を確保
resource "aws_eip" "app_eip" {
  domain = "vpc"
  tags = {
    Name = "hackathon-app-eip"
  }
}

# 2) EIP をインスタンスに関連付け
resource "aws_eip_association" "app_assoc" {
  instance_id   = aws_instance.app_server.id
  allocation_id = aws_eip.app_eip.id
}

##############################
# 出力設定
##############################
output "instance_public_ip" {
  description = "EC2 インスタンスのパブリック IP"
  value       = aws_instance.app_server.public_ip
}

output "instance_public_dns" {
  description = "EC2 インスタンスのパブリック DNS"
  value       = aws_instance.app_server.public_dns
}

output "rds_endpoint" {
  description = "RDS(MySQL) のエンドポイント"
  value       = aws_db_instance.default.address
}