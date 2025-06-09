#!/bin/bash

#-----------------------------------
# 1. OS パッケージの更新と基本ツールのインストール
#-----------------------------------
sudo dnf update -y
sudo dnf install -y git
sudo dnf install -y wget curl vim

#-----------------------------------
# 2. Docker のインストール（Amazon Linux 2023 の場合）
#-----------------------------------
# Amazon Linux 2023 では "yum install docker" が有効
sudo yum install -y docker

# Docker サービスを有効化＆起動
sudo systemctl enable docker
sudo systemctl start docker

# ec2-user を Docker グループに追加する（後で再ログインすれば適用される）
sudo usermod -aG docker ec2-user

#-----------------------------------
# 3. クローン先ディレクトリの準備
#-----------------------------------
# GitHub からアプリケーション（Dockerfile 等）をクローンし、コンテナを構築する
cd /home/ec2-user

# gitクローン
git clone https://github.com/Rikishi-com/3rd_generation_hackathon.git

# 所有権を ec2-user に変えておく
sudo chown -R ec2-user:ec2-user /home/ec2-user/3rd_generation_hackathon

#-----------------------------------
# 4. Docker イメージのビルド & コンテナ起動
#-----------------------------------
cd /home/ec2-user/3rd_generation_hackathon

# リポジトリ直下にDockerfileがあることが前提

# 4.1 Docker イメージをビルド
# django-appは任意名
docker build -t django-app .

# 4.2 環境変数を設定してコンテナを起動
docker run -d \
  --name django_app \
  -p 80:8000 \
  -e DB_HOST=hackathon-mysql-db.ch448uymmqw2.ap-northeast-1.rds.amazonaws.com \
  -e DB_NAME=hackathon-mysql-db \
  -e DB_USER=admin \
  -e DB_PASSWORD=YSSR04hackathon \
  django-app




echo "completed" > /var/log/user_data.log