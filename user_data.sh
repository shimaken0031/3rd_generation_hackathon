#!/bin/bash

#-----------------------------------
# 1. OS パッケージの更新と基本ツールのインストール
#-----------------------------------
sudo dnf update -y
sudo dnf install -y git wget curl vim

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

# 例として "app" というフォルダ名でクローンする
# ↓↓↓ 実際のリポジトリ URL に置き換えてください ↓↓↓
git clone https://github.com/Rikishi-com/3rd_generation_hackathon.git app

# 所有権を ec2-user に変えておく（必須ではありませんが安全のため）
sudo chown -R ec2-user:ec2-user /home/ec2-user/app

#-----------------------------------
# 4. Docker イメージのビルド & コンテナ起動
#-----------------------------------
cd /home/ec2-user/app

# ── 前提：リポジトリ直下に Dockerfile があるものとする ──

# 4.1 Docker イメージをビルド
#    - "django-app" は任意のイメージ名です。お好みで変更してください。
docker build -t django-app .

# 4.2 環境変数を設定してコンテナを起動
#    ここでは例として、RDS(MySQL) のエンドポイント等を環境変数で渡しています。
#    <RDS_ENDPOINT>、<DB_NAME>、<DB_USER>、<DB_PASSWORD> は実際の値に置き換えてください。
docker run -d \
  --name django_app \
  -p 80:8000 \
  -e DB_HOST=<RDS_ENDPOINT> \
  -e DB_NAME=3rd_hackathon_db \
  -e DB_USER=admin \
  -e DB_PASSWORD=YSSR04 \
  django-app

# もし Django 側でマイグレーションや静的ファイルの収集 (collectstatic) が必要であれば、
# 以下のようにコンテナ内で実行する例を参考にしてください。
# （※ イメージ内でコマンドが正しく通るように Dockerfile 側を調整しておく必要があります）
#
# docker exec django_app python manage.py migrate --noinput
# docker exec django_app python manage.py collectstatic --noinput

#-----------------------------------
# 5. （オプション）docker-compose を使いたい場合
#-----------------------------------
# もしリポジトリ内に docker-compose.yml がある場合や、docker-compose を使って複数コンテナを
# 一括管理したい場合は、以下のように docker-compose v2 をインストールして利用できます。
#
# sudo dnf install -y curl
# sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) \
#   -o /usr/libexec/docker/cli-plugins/docker-compose
# sudo chmod +x /usr/libexec/docker/cli-plugins/docker-compose
#
# cd /home/ec2-user/app
# docker compose up -d
#
# ※ ただし、今回のハッカソン用途で単一コンテナ構成なら上記の "docker build / docker run" のみで問題ありません。

#-----------------------------------
# 6. 最後に（ログやデバッグ用に入れておくと便利）
#-----------------------------------
echo "---------- user_data.sh の実行が完了しました ----------"  > /var/log/user_data.log 2>&1