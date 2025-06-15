from django.shortcuts import render
import os
import re
import subprocess
import tempfile
import shutil
import time
import traceback
import math
from reportlab.lib.pagesizes import A4  # A4サイズのページを使用(pip not install reportlabが必要)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont



# pydubは分割処理では不要になったため、コメントアウトまたは削除を検討
# from pydub import AudioSegment 

import openai
from openai import OpenAI

from concurrent.futures import ThreadPoolExecutor, as_completed

from googleapiclient.discovery import build
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

# --- YouTube Data API Client Initialization ---
youtube = build('youtube', 'v3', developerKey=settings.YOUTUBE_API_KEY)

# --- OpenAI API Client Initialization ---
openai_client = None
try:
    print("OpenAI API クライアントを初期化中...")
    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    print("OpenAI API クライアントの初期化に成功しました。")
except Exception as e:
    print(f"OpenAI API クライアントの初期化に失敗しました: {e}")
    print(f"トレースバック:\n{traceback.format_exc()}")
    openai_client = None


class YoutubePaidSummarizerAPI(APIView):
    """
    API to receive a YouTube video link, transcribe its audio using OpenAI Whisper (parallelized),
    and summarize the text using OpenAI API. Also, generates practice problems.
    """

    # --- 定数 ---
    CHUNK_LENGTH_SECONDS = 60 * 2 # 2分 = 120秒ごとに分割
    MAX_WHISPER_WORKERS = 10 # 並行して実行するWhisper API呼び出しの最大数

    def post(self, request, *args, **kwargs):
        youtube_link = request.data.get('link')

        if not youtube_link:
            print("エラー: YouTubeリンクが提供されていません。")
            return Response({"error": "YouTubeリンクが提供されていません。"}, status=status.HTTP_400_BAD_REQUEST)

        video_id = self._extract_video_id(youtube_link)
        if not video_id:
            print(f"エラー: 無効なYouTubeリンクです。動画IDを抽出できませんでした: {youtube_link}")
            return Response({"error": "無効なYouTubeリンクです。動画IDを抽出できませんでした。"}, status=status.HTTP_400_BAD_REQUEST)

        temp_dir = None
        downloaded_audio_filepath = None

        try:
            temp_dir = tempfile.mkdtemp(dir=settings.MEDIA_ROOT)
            print(f"一時ディレクトリを作成しました: {temp_dir}")

            # 1. Get video information using YouTube Data API.
            print("ステップ1: YouTube Data API で動画情報の取得を開始します。")
            try:
                video_response = youtube.videos().list(
                    part='snippet,contentDetails', # contentDetails を追加して動画の長さを取得
                    id=video_id
                ).execute()

                if not video_response.get('items'):
                    print(f"エラー: YouTube Data API: 指定されたIDの動画が見つかりません: {video_id}")
                    return Response({"error": "指定されたIDの動画が見つかりません。"}, status=status.HTTP_404_NOT_FOUND)

                video_item = video_response['items'][0]
                video_snippet = video_item['snippet']
                video_content_details = video_item['contentDetails']

                title = video_snippet.get('title', 'N/A')
                description = video_snippet.get('description', 'N/A')
                # 動画の長さを取得 (ISO 8601形式のDurationを秒に変換)
                duration_iso = video_content_details.get('duration')
                total_duration_seconds = self._parse_iso8601_duration(duration_iso) if duration_iso else 0

                print(f"動画情報取得完了。タイトル: {title}, 長さ: {total_duration_seconds}秒")
            except Exception as e:
                print(f"ステップ1エラー: YouTube Data API で動画情報の取得中にエラーが発生しました: {e}")
                print(f"トレースバック:\n{traceback.format_exc()}")
                return Response({"error": "動画情報の取得に失敗しました。", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 2. Download audio from YouTube video locally using yt-dlp, directly to mp3.
            print("ステップ2: yt-dlp で音声ダウンロードを開始します (MP3形式)。")
            try:
                downloaded_audio_extension = 'mp3'
                downloaded_audio_filename = f"{video_id}_downloaded_audio.{downloaded_audio_extension}"
                downloaded_audio_filepath = os.path.join(temp_dir, downloaded_audio_filename)

                # yt-dlpのオーディオ品質オプションを追加（任意）
                # '192K' など、より低いビットレートを指定することでダウンロードと変換を高速化できる可能性があります
                yt_dlp_command = [
                    'yt-dlp',
                    '-f', 'bestaudio',
                    '--extract-audio',
                    '--audio-format', downloaded_audio_extension,
                    # '--audio-quality', '128K', # 必要であれば追加
                    '-o', downloaded_audio_filepath,
                    youtube_link,
                    '--force-overwrites'
                ]

                print(f"   yt-dlp コマンド実行: {' '.join(yt_dlp_command)}")
                print(f"   subprocess.run 実行時のPATH (yt-dlp): {os.environ.get('PATH')}")
                # capture_output=False にすると、yt-dlpの進捗がリアルタイムで表示される
                subprocess.run(yt_dlp_command, check=True, capture_output=False)

                if not os.path.exists(downloaded_audio_filepath) or os.path.getsize(downloaded_audio_filepath) == 0:
                    raise Exception(f"yt-dlp がオーディオファイルをダウンロードできなかったか、空のファイルです: {downloaded_audio_filepath}")

                print(f"音声ダウンロード完了: {downloaded_audio_filepath}")
            except subprocess.CalledProcessError as e:
                error_output = e.stderr.decode('utf-8') if e.stderr else "(エラー出力なし)"
                print(f"ステップ2エラー: yt-dlp コマンド実行エラー: {e.cmd}")
                print(f"   リターンコード: {e.returncode}")
                print(f"   標準エラー出力:\n{error_output}")
                print(f"トレースバック:\n{traceback.format_exc()}")
                return Response({"error": "動画のダウンロードに失敗しました。", "detail": f"yt-dlp コマンド実行エラー: {e.cmd}. エラー出力: {error_output}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except FileNotFoundError as e:
                print(f"ステップ2エラー: yt-dlp 実行ファイルが見つかりません: {e.filename}")
                print(f"   詳細: {e.strerror}")
                print(f"トレースバック:\n{traceback.format_exc()}")
                return Response({"error": "動画のダウンロードに失敗しました。", "detail": f"yt-dlp 実行ファイルが見つかりません: {e.filename}. PATHが正しく設定されているか確認してください。"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Exception as e:
                print(f"ステップ2エラー: 音声ダウンロード中に予期せぬエラーが発生しました: {e}")
                print(f"トレースバック:\n{traceback.format_exc()}")
                return Response({"error": "音声ダウンロード中にエラーが発生しました。", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # ダウンロードされたMP3ファイルを文字起こしに使用
            converted_audio_filepath = downloaded_audio_filepath

            # 3. Split audio into chunks and transcribe using OpenAI Whisper API in parallel.
            print("ステップ3: 音声ファイルをチャンクに分割し、OpenAI Whisper API で並行して文字起こしを開始します。")
            if openai_client is None:
                print("エラー: OpenAI API クライアントがロードされていません。")
                return Response({"error": "OpenAI API クライアントがロードされていません。設定を確認してください。"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            transcript_text = ""
            try:
                # 音声ファイルをチャンクに分割（ffmpeg直接呼び出し）
                print(f"   音声を {self.CHUNK_LENGTH_SECONDS} 秒ごとに分割中...")
                chunk_files = self._split_audio_ffmpeg( # _split_audio から _split_audio_ffmpeg に変更
                    audio_file_path=converted_audio_filepath,
                    total_duration_seconds=total_duration_seconds, # 動画の総時間を渡す
                    chunk_length_seconds=self.CHUNK_LENGTH_SECONDS,
                    output_dir=temp_dir
                )
                print(f"   {len(chunk_files)} 個のチャンクを作成しました。")

                if not chunk_files:
                    print("警告: 分割された音声チャンクがありません。文字起こしできません。")
                    transcript_text = ""
                else:
                    # 並行して文字起こしを実行
                    transcription_results = [None] * len(chunk_files) # 順序を保持するリスト

                    with ThreadPoolExecutor(max_workers=self.MAX_WHISPER_WORKERS) as executor:
                        future_to_chunk = {
                            executor.submit(self._transcribe_audio_chunk_parallel, chunk_info): chunk_info
                            for chunk_info in chunk_files
                        }

                        for future in as_completed(future_to_chunk):
                            chunk_info = future_to_chunk[future]
                            try:
                                result = future.result()
                                if "error" in result:
                                    print(f"   チャンク {result['index']} の文字起こし中にエラーが発生しました: {result['error']}")
                                    transcription_results[result["index"]] = f"[文字起こしエラー: {result['error']}]"
                                else:
                                    transcription_results[result["index"]] = result["text"]
                            except Exception as exc:
                                print(f"   チャンク {chunk_info['index']} の処理中に予期せぬ例外が発生しました: {exc}")
                                transcription_results[chunk_info["index"]] = f"[不明な文字起こしエラー: {exc}]"

                    # 全てのチャンクの文字起こし結果を結合
                    full_transcript_parts = [text for text in transcription_results if text is not None]
                    transcript_text = "\n".join(full_transcript_parts).strip()

                print("文字起こし完了。")

                if not transcript_text:
                    print("警告: 音声から文字起こしテキストを取得できませんでした。")
                    return Response({
                        "title": title,
                        "description": description,
                        "transcript": "",
                        "summary": "動画の音声から文字起こしテキストを取得できませんでした。要約を生成できません。",
                        "practice_problems": "文字起こしテキストがないため、練習問題は生成できません。",
                    }, status=status.HTTP_200_OK)

            except Exception as e:
                print(f"ステップ3エラー: Whisper API で文字起こし中にエラーが発生しました: {e}")
                print(f"トレースバック:\n{traceback.format_exc()}")
                return Response({"error": "音声の文字起こしに失敗しました。", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 4. Generate summary using OpenAI API.
            print("ステップ4: OpenAI API で要約を開始します。")
            if openai_client is None:
                print("エラー: OpenAI API クライアントがロードされていません。")
                return Response({"error": "OpenAI API クライアントがロードされていません。設定を確認してください。"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            try:
                prompt_summary = f"あなたは優秀なテクニカルライターとして、これから渡す YouTube 動画のタイトルと文字起こしデータを読み取り、動画の要点を 3〜5 行で簡潔に記述し、読者が動画を見なくてもどの分野（例：プログラミング、AI、数学、物理、ガジェットレビュー など）で何をしている動画かが一目で分かるように示し、数学または物理の問題解説であれば解法プロセスを手順ごとに箇条書きで必要に応じて数式も使って詳しく説明し、それ以外の場合は技術的・専門的ポイントを中心に雑談や余談を省いてまとめてください。\n\n動画タイトル: {title}\n\n文字起こしデータ:\n{transcript_text}\n\n要約:"
                print("   OpenAI API (要約) リクエスト送信中...")
                response_summary_openai = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "あなたは動画の内容を要約して参考書を作るアシスタントです。"},
                        {"role": "user", "content": prompt_summary}
                    ],
                    max_tokens=1000,
                    temperature=0.7,
                )
                summary = response_summary_openai.choices[0].message.content.strip()
                print("要約完了。")
            except Exception as e:
                print(f"ステップ4エラー: OpenAI API で要約生成中にエラーが発生しました: {e}")
                print(f"トレースバック:\n{traceback.format_exc()}")
                return Response({"error": "要約の生成に失敗しました。", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 5. Generate practice problems using OpenAI API.
            print("ステップ5: OpenAI API で練習問題の生成を開始します。")
            practice_problems = "生成できませんでした。"
            if openai_client: # OpenAIクライアントが利用可能(≠None)な場合のみ実行
                    # 文字列の前のfはフォーマット文字列を示す．（文字列の中に変数を埋め込むことが可能）
                prompt_problems = (
                    f"あなたは優秀な作問者として、与えられた YouTube 動画のタイトルと文字起こしを読み取り、"
                    f"動画が数学・物理に関する内容であれば、内容に基づいて日本語で練習問題を5問作成してください。"
                    f"その際、通常の記述式問題（例：式を解く・定理を説明するなど）を用いてください。\n"
                    f"一方、動画が数学・物理以外の内容であれば、その分野に関連した**知識の穴埋め問題**を5問作成してください。"
                    f"例えば、歴史や社会に関する内容であれば、用語や人名、出来事などを空欄にした文を提示し、それに対応する正答を用意してください。\n"
                    f"まず 「問題文のみ」 のパートに５問を列挙し、続く 「問題と解答」 のパートでは、"
                    f"先程生成した5問と全く同じ各問題の直後に導出過程を詳述した解答を併記して提示してください。\n\n"
                    f"回答は以下の形式で出力してください。\n\n"
                    f"(物理・数学の場合かつ問題文のみの場合):\n"
                    f"問題1:[問題文を記載]\n"
                    f"問題2:[問題文を記載]\n"
                    f"問題3:[問題文を記載]\n"
                    f"問題4:[問題文を記載]\n"
                    f"問題5:[問題文を記載]\n\n"
                    f"(物理・数学の場合かつ問題と解答の場合):\n"
                    f"問題1:[問題文を記載]\n"
                    f"解答1:[問題の解答と導出過程を詳述]\n"
                    f"問題2:[問題文を記載]\n"
                    f"解答2:[問題の解答と導出過程を詳述]\n"
                    f"問題3:[問題文を記載]\n"
                    f"解答3:[問題の解答と導出過程を詳述]\n"
                    f"問題4:[問題文を記載]\n"
                    f"解答4:[問題の解答と導出過程を詳述]\n"
                    f"問題5:[問題文を記載]\n"
                    f"解答5:[問題の解答と導出過程を詳述]\n\n"
                    f"(物理・数学以外の場合かつ問題文のみの場合):\n"
                    f"問題:[穴埋め問題文を記載]\n\n"
                    f"解答:[穴埋めされていない全文を記載(穴埋めになっていた箇所には，同様の位置に括弧を付けて ([穴埋め箇所の解答を記載])) ]\n"
                    f"動画タイトル: {title}\n\n"
                    f"文字起こしデータ:\n{transcript_text}\n\n"
                    f"練習問題と解答:"
                )                
                print("   OpenAI API (練習問題) リクエスト送信中...")
                try:
                    response_problems_openai = openai_client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": "あなたは動画内容から練習問題を作成するアシスタントです。"}, #role:systemはAIにどんな役割を与えるかを指定
                            {"role": "user", "content": prompt_problems} #role:userはユーザからの入力を示す
                        ],
                        max_tokens=1500, # 出力される最大トークン数（日本語で約3000字）
                        temperature=0.7, # 生成の多様性を制御するパラメータ（堅い：0.0〜1.0：創造的）
                    )
                    practice_problems = response_problems_openai.choices[0].message.content.strip()
                    print("練習問題の生成完了。")

                    self.create_graph(practice_problems, f"/app/medias/{video_id}_graph.mp4")

                    problem_pdf_path = os.path.join(settings.PDF_ROOT, f"{video_id}_problems.pdf")
                    answer_pdf_path = os.path.join(settings.PDF_ROOT, f"{video_id}_answers.pdf")
                    self.save_problem_only_pdf(practice_problems, problem_pdf_path)
                    self.save_answer_only_pdf(practice_problems, answer_pdf_path)
                except Exception as problem_e:
                    print(f"ステップ5エラー: 練習問題の生成中にエラーが発生しました: {problem_e}")
                    print(f"トレースバック:\n{traceback.format_exc()}")
                    practice_problems = f"練習問題の生成中にエラーが発生しました: {problem_e}"
            else:
                print("警告: OpenAI API クライアントが利用できないため、練習問題は生成されません。")
                # 6. Return the response with title, description, transcript, summary, and practice problems.

            return Response({
                "title": title,
                "description": description,
                "transcript": transcript_text,
                "summary": summary,
                "practice_problems": practice_problems
            }, status=status.HTTP_200_OK)

        except Exception as e:
            traceback_str = traceback.format_exc()
            print(f"API処理中に予期せぬクリティカルエラーが発生しました: {e}")
            print(f"トレースバック:\n{traceback_str}")
            return Response({"error": "処理中に予期せぬクリティカルエラーが発生しました。", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                print(f"一時ディレクトリを削除します: {temp_dir}")
                shutil.rmtree(temp_dir)
    
    # --- グラフ必要性判断メソッド ---
    def judge_necesally_graph(self,text):
        """
        文字起こしテキストにグラフが必要かどうかを判断する。
        グラフが必要な場合はTrue、不要な場合はFalseを返す。
        """

        # ここでは、グラフが必要な条件を定義する。
        keywords = ["グラフ", "図", "チャート", "プロット", "図表", "グラフ化", "可視化", "データの可視化", "グラフを描く", "グラフを作成"]
        judge_from_txt = any(keyword in text for keyword in keywords)

        if openai_client is None:
            print("OpenAIクライアントが未初期化のため、グラフの必要性を判断できません。")
            return judge_from_txt

        try:
            judge_from_openai_client = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "あなたは優秀なテクニカルライターとして、与えられた文字起こしテキストにグラフが必要かどうかを判断してください。"},
                    {"role": "user", "content": f"以下の文字起こしテキストにグラフが必要ですか？必要な場合は「True」、不要な場合は「False」と答えてください。また確実に，「True」or「False」の２択で解答しなさい．そのほかの文字列は一切不要である．\n\n{text}"}
                ],
                max_tokens=10,
                temperature=0.0,  # 確定的な応答を得るために独創性を0に設定
            )
            result_from_openai = judge_from_openai_client.choices[0].message.content.strip()
            result_from_openai = result_from_openai == "True"
        except Exception as e:
            print(f"OpenAI APIでのグラフ必要性判断中にエラーが発生しました: {e}")
            result_from_openai = False

        if ((judge_from_txt) and (result_from_openai)) == "True":
            print("グラフが必要と判断されました。")
            return True
        else:
            print("グラフは不要と判断されました。")
            return False


    # --- PDF変換メソッド ---
    # このメソッドは、文字起こしテキストをPDFファイルとして保存するために使用される。
    # ここでは、問題文のみ、解答のみ、または全文をPDFとして保存するためのメソッドを定義する。
    # 既に出力先まで設定してあって出力されることは確認済みです．（上野より）

    def convert_to_pdf(self, text, filename):   #PDF変換メソッド
        """
        与えられたテキストをPDFファイルとして保存する。
        :param text: PDFに書き込む文字列
        :param filename: 出力先ファイルパス（フルパスで指定）
        """

        try:
            c = canvas.Canvas(filename, pagesize=A4)
            width, height = A4
            margin = 50
            y = height - margin
            line_height = 14

            for line in text.split('\n'):   # テキストを行ごとに分割
                if y < margin:
                    c.showPage()    # ページの下端に到達したら新しいページを作成
                    y = height - margin
                c.drawString(margin, y, line)   # 行をPDFに書き込む
                y -= line_height    # 次の行へ進む

            c.save()
            print(f"PDFとして保存しました: {filename}") # PDF保存完了メッセージ(フルパス含)
            
        except Exception as e:
            print(f"PDF生成中にエラーが発生しました: {e}")


    def save_problem_only_pdf(self, full_text, filename):
        problem_lines = []
        for line in full_text.split('\n'):
            if line.startswith("問題") and "解答" not in line:
                problem_lines.append(line)
        self.convert_to_pdf("\n".join(problem_lines), filename)

    def save_answer_only_pdf(self, full_text, filename):
        answer_started = False
        answer_lines = []
        for line in full_text.split('\n'):
            if line.strip().startswith("解答"):
                answer_started = True
            if answer_started:
                answer_lines.append(line)
        self.convert_to_pdf("\n".join(answer_lines), filename)

    font_path = os.path.join(settings.BASE_DIR, "pdfs", "fonts", "ipaexm.ttf")
    pdfmetrics.registerFont(TTFont("IPAexGothic", font_path))

    def convert_to_pdf(self, text, filename):
        c = canvas.Canvas(filename, pagesize=A4)
        width, height = A4
        c.setFont("IPAexGothic", 12)  # 日本語対応フォント

        y = height - 50  # 上から描画開始
        for line in text.split("\n"):
            if y < 50:
                c.showPage()
                c.setFont("IPAexGothic", 12)
                y = height - 50
            c.drawString(50, y, line)
            y -= 20

        c.save()


    # --- グラフ生成メソッド ---
    def create_graph(self, text, filename):
        """
        文字起こしテキストからグラフを生成し、PDFとして保存する。
        グラフが必要な場合はTrueを返す。
        """

        question_prompt = (
            f"以下のテキストからグラフを生成するための数式を抽出してください。"
            f"条件として，数式はlatex形式で出力しなければならない．"
            f"入力は5問の問題とその解答である．\n"
            f"各問題に対応する数式は，複数あっても1行で出力しなければならない．"
            f"グラフが必要な場合は数式を、不要な場合は「None」と解答すること。\n\n"
            f"その際，異なる数式ごとに[,]で区切ること（数式が必要ない問題は空行にする）"  #半角カンマ
            f"つまり出力は五行である必要がある．\n\n"
            f"{text}\n\n"
        )

        if not self.judge_necesally_graph(text):
            print("グラフは不要と判断されました。")
            return False
        
        math_from_text_openai_client = openai_client.chat.completions.create(

            model="gpt-4",
            messages=[
                {"role": "system", "content": "あなたは優秀な数学者として、与えられた文字起こしテキストからグラフを生成するための数式を抽出してください。"},
                {"role": "user", "content" : question_prompt}
            ],
            max_tokens=200,
            temperature=0 # 確定的な応答を得るために独創性を0に設定
        )
        result = math_from_text_openai_client.choices[0].message.content.rstrip("\r\n")

        separated_results = result.split("\n")  # 改行で分割

        for idx, line in enumerate(separated_results):
            latex_expr = line.strip()

            if latex_expr == "None" or latex_expr == "":
                print("グラフは不要と判断されました。")
                continue

            print(f"グラフを生成するための数式: {latex_expr}")

            manim_code = f"""       # Manimコードを生成（描写→表示→消す）
        from manim import *

        class FormulaScene(Scene):
            def construct(self):
                tex = MathTex(r\"\"\"{latex_expr}\"\"\")
                tex.scale(1.2)
                self.play(Write(tex))
                self.wait(1)
                self.play(FadeOut(tex))
        """

            with tempfile.TemporaryDirectory() as tmpdir:
                manim_file_path = os.path.join(tmpdir, "formula_scene.py")
                with open(manim_file_path, "w", encoding="utf-8") as f:
                    f.write(manim_code)

                try:
                    # filename: ex) "output.mp4" → "output_0.mp4", "output_1.mp4", ...
                    output_dir = os.path.join("/app/medias")
                    os.makedirs(output_dir, exist_ok=True)  # ディレクトリが無ければ作成

                    # 出力ファイル名を構築（例: /app/medias/graph_0.mp4）
                    output_filename = os.path.join(output_dir, f"graph_{idx}.mp4")

                    subprocess.run([
                        "manim",
                        "-qk",
                        "--format", "mp4",
                        manim_file_path,
                        "FormulaScene",
                        "-o", os.path.basename(output_filename)
                    ], cwd=tmpdir, check=True)

                    output_path = os.path.join(tmpdir, "media", "videos", "formula_scene", "1080p60", os.path.basename(output_filename))
                    if os.path.exists(output_path):
                        os.rename(output_path, output_filename)
                        print(f"グラフをmp4として保存しました: {output_filename}")
                    else:
                        print(f"出力ファイルが見つかりませんでした: {output_filename}")
                except subprocess.CalledProcessError as e:
                    print(f"Manim 実行エラー: {e}")

        return True

    def _extract_video_id(self, youtube_link):
        """
        YouTubeリンクから動画IDを抽出する
        """
        match_v = re.search(r'(?:v=|youtu\.be\/|embed\/|v\/|watch\?v%3D|&v=|%2Fv%2F)([a-zA-Z0-9_-]{11})', youtube_link)
        if match_v:
            return match_v.group(1)

        match_short = re.search(r'youtu\.be\/([a-zA-Z0-9_-]{11})', youtube_link)
        if match_short:
            return match_short.group(1)

        match_embed = re.search(r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})', youtube_link)
        if match_embed:
            return match_embed.group(1)

        return None

    def _parse_iso8601_duration(self, duration_str):
        """
        ISO 8601形式の期間文字列 (例: PT1H2M3S) を秒数に変換する
        """
        # 正規表現でH (時間), M (分), S (秒) を抽出
        hours = re.search(r'(\d+)H', duration_str)
        minutes = re.search(r'(\d+)M', duration_str)
        seconds = re.search(r'(\d+)S', duration_str)

        total_seconds = 0
        if hours:
            total_seconds += int(hours.group(1)) * 3600
        if minutes:
            total_seconds += int(minutes.group(1)) * 60
        if seconds:
            total_seconds += int(seconds.group(1))

        return total_seconds

    def _split_audio_ffmpeg(self, audio_file_path, total_duration_seconds, chunk_length_seconds, output_dir):
        """
        ffmpegコマンドを直接使用して音声ファイルを指定された秒数のチャンクに分割し、チャンクファイルのリストを返す。
        この方法はpydubを使用するよりも高速である可能性があります。
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        chunks = []
        # 総再生時間からチャンク数を計算
        num_chunks = math.ceil(total_duration_seconds / chunk_length_seconds)

        for i in range(num_chunks):
            start_time_seconds = i * chunk_length_seconds

            # チャンクの終了時間は、次のチャンクの開始時間、または総時間まで
            # durationは、現在のチャンクの長さ
            duration_current_chunk = chunk_length_seconds
            if start_time_seconds + chunk_length_seconds > total_duration_seconds:
                duration_current_chunk = total_duration_seconds - start_time_seconds
                if duration_current_chunk <= 0: # 最後のチャンクが既に終わっている場合
                    break

            chunk_file_path = os.path.join(output_dir, f"chunk_{i:04d}.mp3")

            # ffmpegコマンド:
            # -i <入力ファイル>
            # -ss <開始時刻> (秒またはhh:mm:ss形式)
            # -t <期間> (秒またはhh:mm:ss形式)
            # -c:a copy: オーディオストリームを再エンコードせずにコピー (最速)
            # -map_chapters -1: チャプターメタデータをコピーしない (不要な処理を避ける)
            # -y: 出力ファイルを上書き
            ffmpeg_command = [
                'ffmpeg',
                '-i', audio_file_path,
                '-ss', str(start_time_seconds),
                '-t', str(duration_current_chunk),
                '-c:a', 'copy', # 音声ストリームをコピー（再エンコードしない）
                '-map_chapters', '-1', # 必要であればチャプターメタデータをコピーしない
                '-y', # 既存ファイルの上書きを許可
                chunk_file_path
            ]

            try:
                print(f"   ffmpeg でチャンク {i} を作成中: {start_time_seconds}s - {start_time_seconds + duration_current_chunk}s")
                subprocess.run(ffmpeg_command, check=True, capture_output=True) # 標準出力をキャプチャしてログを抑制
                chunks.append({"index": i, "path": chunk_file_path})
            except subprocess.CalledProcessError as e:
                error_output = e.stderr.decode('utf-8') if e.stderr else "(エラー出力なし)"
                print(f"警告: ffmpeg でチャンク {i} の作成中にエラーが発生しました: {e}")
                print(f"    コマンド: {' '.join(ffmpeg_command)}")
                print(f"    エラー出力:\n{error_output}")
                print(f"トレースバック:\n{traceback.format_exc()}")
                # エラーが発生したチャンクはスキップ
                continue
            except FileNotFoundError:
                print(f"エラー: ffmpeg 実行ファイルが見つかりません。PATHが正しく設定されているか確認してください。")
                raise # ffmpegがない場合は致命的なエラーとして再raise

        return chunks

    def _transcribe_audio_chunk_parallel(self, chunk_info):
        """
        単一の音声チャンクをWhisper APIに送信し、文字起こし結果を返す。
        並行処理のために設計されたヘルパーメソッド。
        """
        chunk_index = chunk_info["index"]
        chunk_path = chunk_info["path"]

        print(f"   チャンク {chunk_index} の文字起こしを開始します ({os.path.basename(chunk_path)})...")

        try:
            if openai_client is None:
                return {"index": chunk_index, "text": "", "error": "OpenAIクライアントが初期化されていません。"}

            # ファイルサイズチェック (Whisper APIの制限25MB)
            file_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
            if file_size_mb > 25:
                # このケースはffmpegのc:a copyでは発生しにくいが、念のため
                print(f"   警告: チャンク {chunk_index} のファイルサイズが25MBを超えています ({file_size_mb:.2f}MB)。スキップします。")
                return {"index": chunk_index, "text": "", "error": f"ファイルサイズが25MBを超過 ({file_size_mb:.2f}MB)"}


            with open(chunk_path, "rb") as audio_file:
                transcript = openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="ja"
                )
            print(f"   チャンク {chunk_index} の文字起こしが完了しました。")
            return {"index": chunk_index, "text": transcript.text}
        except openai.APIError as e:
            print(f"   チャンク {chunk_index} でOpenAI APIエラーが発生しました: {e}")
            return {"index": chunk_index, "text": "", "error": f"OpenAI APIエラー: {e.code} - {e.message}"}
        except Exception as e:
            print(f"   チャンク {chunk_index} の文字起こし中にエラーが発生しました: {e}")
            print(f"トレースバック:\n{traceback.format_exc()}")
            return {"index": chunk_index, "text": "", "error": str(e)}