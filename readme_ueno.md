# ローカル環境でDockerfileを使って環境構築をしたい場合
MacとWindowsで違うかもしれないけれど，多分似通ってると思う．
**Dockerはインストールしていることが前提**

---

### 1.ターミナル/コマンドプロンプト上で`git clone`する
- `git clone`のコマンドは以下の通り

```bash
git clone https://github.com/Rikishi-com/3rd_generation_hackathon
```
- クローンしたいディレクトリにあらかじめ`cd`で飛んでおく

####　**GitHub**からクローンしたファイルは同一ディレクトリに保存する(以下のような構成にして)
```tree
├── 3rd_hackathon.pem
├── db.sqlite3
├── Dockerfile
├── main.tf
├── manage.py
├── readme_ueno.md
├── requirements.txt
├── summarizer_app
│   ├── __init__.py
│   ├── __pycache__
│   │   ├── __init__.cpython-312.pyc
│   │   ├── admin.cpython-312.pyc
│   │   ├── apps.cpython-312.pyc
│   │   ├── models.cpython-312.pyc
│   │   ├── urls.cpython-312.pyc
│   │   └── views.cpython-312.pyc
│   ├── admin.py
│   ├── apps.py
│   ├── migrations
│   │   ├── __init__.py
│   │   └── __pycache__
│   │       └── __init__.cpython-312.pyc
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
├── temp
│   └── tmpi92gownf
│       ├── chunk_0000.mp3
│       ├── chunk_0001.mp3
│       ├── chunk_0002.mp3
│       ├── chunk_0003.mp3
│       ├── chunk_0004.mp3
│       ├── chunk_0005.mp3
│       ├── chunk_0006.mp3
│       └── XljbxPWvBLA_downloaded_audio.mp3
├── user_data.sh
├── variables.tf
├── vpc.tf
└── youtube_summarizer_project
    ├── __init__.py
    ├── __pycache__
    │   ├── __init__.cpython-312.pyc
    │   ├── settings.cpython-312.pyc
    │   ├── urls.cpython-312.pyc
    │   └── wsgi.cpython-312.pyc
    ├── asgi.py
    ├── settings.py
    ├── urls.py
    └── wsgi.py

```

---

### 2.dockerfileを使える形にする

#### 次のコマンドを順に実行していく
コピーでOK

---

**1**
```bash
docker build -t my-django-app .
```
- 初回はだいぶ時間かかります（キャッシュが残ってない場合，エラーなんじゃねって思うぐらい時間かかる場合があります．エラーっていう文字が出ない限り放置してください）
- `Dockerfile`があるディレクトリに移動してこのコマンドを実行する
- `my-django-app`は任意の名前でOK
<br>

**2**
```bash
docker run -dit -p 8000:8000 --name my_django_app my-django-app
```
- コンテナ起動するために使う
- `my_django_app`は任意でOK，`my-django-app`は上で付けた名前と合わせて
<br>

**4**
```bash
docker exec -it my_django_app bash
```
- 起動中のコンテナのコマンドラインに入る
- `my_dango_app`は上で付けた名前

**3**
```bash
python manage.py runserver 0.0.0.0:8000
```
- サーバ起動のコマンド
<br>

**4. `necessary.zip`内に含まれるファイルをコンテナ内にコピーする**
```bash
docker cp <ローカルのパス> <コンテナ名またはID>:<コンテナ内のパス>
```
- ローカル→コンテナ(**今回はこの操作のみ**)
- `test-753cb-c211d5dea50e.json`と`.env`，`ipaexm.ttf`の3つのファイルをコピーするため，それぞれのパスして実行する
- `test-753cb-c211d5dea50e.json`と`.env`は/appでOK
- `ipaexm.ttf`は/app/pdfs/fonts/にいれて
- ディレクトリがない場合は次のコマンドで作成して

### ディレクトリ作成方法
前提としてDockerコンテナ内で打つコマンドです
```bash
mkdir pdfs
cd pdfs
mkdir fonts
```
- これを実行したら再度上のコマンドで，パスを指定する

---

```bash
docker cp <コンテナ名またはID>:<コンテナ内のパス> <ローカルのパス>
```
- コンテナ→ローカル(**今回は使わない**)

---

### コンテナ名を忘れたとき
以下のコマンドを使って確認して
```bash
docker container ls
```
- `NAME`ってところにコマンド名が書いてあります．
- これで出なかったときはコンテナが動いていない証拠

### コンテナが動いていないとき
以下のコマンドでコンテナの状態を確認する
```bash
docker container ls -a
```
- Exitって書いてあったら動いてない
- このコマンドでもなかったらコンテナが作成できていない

### 作成済みで動いていないコンテナの動かし方
以下のコマンドでコンテナを実行させる
```bash
docker start <コンテナ名>
```

### ポートが使われていますと出たときの対処法
一旦コンテナを再起動させる．こうするとだいたい治ります
```bash
docker restart <コンテナ名>
```


---

### Postmanを使って実行する
以下の写真のとおりに設定する
<br>
![Postman設定](postman_setting.jpg)

---

#### コピペ用

```POST
http://0.0.0.0:8000/summarize_paid_audio/
```
- POSTの部分

<br>

```bash
{
    "link" :"https://youtu.be/4qS1Mlb2v1w?si=XOcpTX2quypa4T84Ω"
}
```
- リンクは一例（あきとんとんの北海道の入試解説）
