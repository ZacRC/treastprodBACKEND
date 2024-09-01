import os
from django.shortcuts import render
from django.views.generic import TemplateView
from django.views.decorators.cache import never_cache
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from .serializers import UserSerializer, AudioFileSerializer, TranscriptionSerializer
from .models import AudioFile, Transcription
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from moviepy.editor import VideoFileClip
from openai import OpenAI
import openai
from django.conf import settings

from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(username=username, password=password)
    if user:
        refresh = RefreshToken.for_user(user)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })
    return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_user(request):
    try:
        refresh_token = request.data["refresh_token"]
        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response(status=status.HTTP_205_RESET_CONTENT)
    except Exception as e:
        return Response(status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_file(request):
    files = request.FILES.getlist('file')  # Get all uploaded files
    uploaded_files = []
    for file in files:
        serializer = AudioFileSerializer(data={'file': file})
        if serializer.is_valid():
            serializer.save(user=request.user)
            uploaded_files.append(serializer.data)
    return Response(uploaded_files, status=status.HTTP_201_CREATED)

def convert_video_to_audio(video_path, audio_path):
    video = VideoFileClip(video_path)
    audio = video.audio
    audio.write_audiofile(audio_path)
    video.close()
    audio.close()

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def process_files(request):
    audio_files = AudioFile.objects.filter(user=request.user)
    all_transcriptions = []
    temp_files = []

    try:
        for audio_file in audio_files:
            file_path = audio_file.file.path
            file_extension = os.path.splitext(file_path)[1].lower()

            if file_extension in ['.mp4', '.avi', '.mov']:
                audio_path = os.path.splitext(file_path)[0] + '.mp3'
                convert_video_to_audio(file_path, audio_path)
                file_path = audio_path
                temp_files.append(audio_path)

            with open(file_path, 'rb') as audio:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    response_format="text"
                )
                transcription, created = Transcription.objects.update_or_create(
                    audio_file=audio_file,
                    defaults={'text': transcript}
                )
                all_transcriptions.append(f"File: {audio_file.file.name}\nTranscription: {transcription.text}\n\n")

        combined_transcription = ''.join(all_transcriptions)

        assistant = client.beta.assistants.retrieve("asst_NfBwpL6Gn1rTVI7yyYc3LDpI")
        thread = client.beta.threads.create()
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=combined_transcription
        )
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id
        )

        while run.status != 'completed':
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        assistant_response = messages.data[0].content[0].text.value

        return Response({'response': assistant_response}, status=status.HTTP_200_OK)

    finally:
        # Clean up temporary files
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        
        # Delete processed audio files
        for audio_file in audio_files:
            file_path = audio_file.file.path
            if os.path.exists(file_path):
                os.remove(file_path)
            audio_file.delete()

        # Delete transcriptions
        Transcription.objects.filter(audio_file__in=audio_files).delete()

index_view = never_cache(TemplateView.as_view(template_name='index.html'))