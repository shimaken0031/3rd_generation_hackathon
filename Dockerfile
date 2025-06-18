# syntax=docker/dockerfile:1

# ───────────────────────────────
#  ベースイメージ
# ───────────────────────────────
FROM python:3.12-slim AS base

# 環境変数：ログ即時出力 & .pyc 抑制
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ───────────────────────────────
#  OS 依存パッケージ
#   • MySQL ヘッダー   : default-libmysqlclient-dev
#   • ffmpeg CLI       : ffmpeg
#   • iconv 変換工具   : gettext-base（iconv が含まれる）
# ───────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libcairo2-dev \
    libpango1.0-dev \
    python3-dev \
    default-libmysqlclient-dev \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-latex-recommended \
    ffmpeg \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

# ───────────────────────────────
#  Python 依存パッケージ
#   requirements.txt は UTF-16 LE のため変換
# ───────────────────────────────
COPY requirements.txt /tmp/requirements.utf16.txt

RUN iconv -f utf-16le -t utf-8 /tmp/requirements.utf16.txt -o /tmp/requirements.txt
RUN cat /tmp/requirements.txt
RUN pip install --upgrade pip
RUN pip install -r /tmp/requirements.txt
RUN pip install reportlab
RUN pip install manim
RUN rm -rf /root/.cache/pip /tmp/requirements*.txt

# ───────────────────────────────
#  アプリケーションコード
# ───────────────────────────────
COPY . /app

# ───────────────────────────────
#  ポート & 起動コマンド（開発用）
# ───────────────────────────────
EXPOSE 8000
CMD ["bash"]