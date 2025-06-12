from django.shortcuts import render
import os
import re
import subprocess
import tempfile
import shutil
import time
import traceback
import math

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
                prompt_summary = f"以下のYouTube動画の文字起こしデータとタイトルに基づいて、日本語で要点を簡潔にまとめてください。これを見たときにどのような分野でどのようなことをやっているのか読者がわかるようにまとめてください。数学や物理学の問題の時はその手順を細かく解説してください。\n\n動画タイトル: {title}\n\n文字起こしデータ:\n{transcript_text}\n\n要約:"
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
            if openai_client:
                prompt_problems = f"以下のYouTube動画の文字起こしデータとタイトルを参考に、数学や物理の動画であれば、その内容に基づいた練習問題を日本語で5問作成してください。解答も一緒に提供してください。解答を作成する際に途中の導出方法も細かく記述してください。その他の分野で知識問題を作成するときは動画に出てきた分野の範囲において穴埋め問題を作成してください。その答えも一緒に提供してください。\n\n動画タイトル: {title}\n\n文字起こしデータ:\n{transcript_text}\n\n練習問題と解答:"
                print("   OpenAI API (練習問題) リクエスト送信中...")
                try:
                    response_problems_openai = openai_client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": "あなたは動画内容から練習問題を作成するアシスタントです。"},
                            {"role": "user", "content": prompt_problems}
                        ],
                        max_tokens=1500,
                        temperature=0.7,
                    )
                    practice_problems = response_problems_openai.choices[0].message.content.strip()
                    print("練習問題の生成完了。")
                except Exception as problem_e:
                    print(f"ステップ5エラー: 練習問題の生成中にエラーが発生しました: {problem_e}")
                    print(f"トレースバック:\n{traceback.format_exc()}")
                    practice_problems = f"練習問題の生成中にエラーが発生しました: {problem_e}"
            else:
                print("警告: OpenAI API クライアントが利用できないため、練習問題は生成されません。")

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