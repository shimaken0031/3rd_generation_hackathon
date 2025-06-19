# summarizer_app/urls.py

from django.urls import path
from .views import YoutubePaidSummarizerAPI, AnswerProcessingAPI 

urlpatterns = [
    path('summarize_paid_audio/', YoutubePaidSummarizerAPI.as_view(), name='summarize_youtube_paid_audio'),
    path('process-answer/', AnswerProcessingAPI.as_view(), name='process_answer'), 
]