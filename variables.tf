##############################
# 変数定義
##############################

variable "region" {
  description = "AWS のリージョン（デフォルトで ap-northeast-1）"
  type        = string
  default     = "ap-northeast-1"
}

variable "ami" {
  description = "EC2 用の AMI ID（後で指定）"
  type        = string
  default     = "ami-027fff96cc515f7bc" # Amazon Linux 2023 の AMI
}

variable "instance_type" {
  description = "EC2 インスタンスタイプ（t2.micro など）"
  type        = string
  default     = "t2.micro"
}

variable "key_name" {
  description = "SSH キーペア名"
  type        = string
}

variable "vpc_id" {
  description = "作成済み VPC の ID"
  type        = string
}

variable "public_subnet_id" {
  description = "EC2 を立てるパブリックサブネットの ID"
  type        = string
}

variable "db_subnet_ids" {
  description = "RDS 用 DB サブネットグループに用いるサブネット ID のリスト"
  type        = list(string)
}

variable "db_name" {
  description = "RDS(MySQL) のデータベース名"
  type        = string
  default     = "third_hackathon_db"
}

variable "db_username" {
  description = "RDS(MySQL) のユーザー名"
  type        = string
  default     = "admin"
}

variable "db_password" {
  description = "RDS(MySQL) のパスワード"
  type        = string
}

variable "project" {
  description = "プロジェクト名"
  type        = string
  default     = "third_hackathon"
}

variable "environment" {
  description = "環境名"
  type        = string
  default     = "dev"
}