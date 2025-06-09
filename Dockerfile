# ┌───────────────────────────────────────────────────┐
# │  Dockerfile                                      │
# └───────────────────────────────────────────────────┘

# 1) ベースイメージとして Python 3.10 のスリム版を指定
FROM python:3.10

# 2) コンテナ内の作業ディレクトリを /app に設定
WORKDIR /app

# 3) 必要な OS パッケージをインストール
#    （MySQL ドライバをビルドするためのヘッダーを含む）
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      default-libmysqlclient-dev \
      pkg-config \
 && rm -rf /var/lib/apt/lists/*

# 4) pip をアップグレードし、Django と MySQL ドライバをインストール
RUN pip install --upgrade pip \
 && pip install Django==5.2.1 mysqlclient

# 5) ローカルのコード（manage.py や settings.py、app/, myproject/ など）を
#    コンテナ内 /app にコピー
COPY . /app

# 6) Django の開発サーバーが使うポートを開放
EXPOSE 8000

# 7) デフォルトの起動コマンドとして Django の開発サーバーを指定
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]