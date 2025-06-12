from django.urls import path
from .views import YoutubePaidSummarizerAPI # クラス名を変更

urlpatterns = [
    path('summarize_paid_audio/', YoutubePaidSummarizerAPI.as_view(), name='summarize_youtube_paid_audio'),
]