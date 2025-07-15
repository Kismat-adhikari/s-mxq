
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import os
import time
import requests
import yt_dlp
from pathlib import Path
import threading
import uuid
import tempfile
from dotenv import load_dotenv


load_dotenv()
app = Flask(__name__)

@app.errorhandler(500)
def internal_server_error(e):
    # Log the error for debugging purposes
    app.logger.exception('An internal server error occurred')
    return jsonify(error='Internal Server Error', message=str(e)), 500

# Store transcription results in memory (use Redis/database in production)
transcription_results = {}


# Load API keys from .env file
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Validate API keys
if not ASSEMBLYAI_API_KEY:
    raise ValueError("ASSEMBLYAI_API_KEY not found in environment variables. Please set it in your .env file.")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in environment variables. Please set it in your .env file.")

def download_audio(youtube_url, output_path):
    """Download audio from YouTube video"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path.replace('.mp3', '.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        # Add these options to fix 403 errors
        'extractor_args': {
            'youtube': {
                'skip': ['dash', 'hls']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        },
        'cookiefile': None,
        'no_warnings': True,
        'ignoreerrors': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])
    
    return output_path

def upload_to_assemblyai(file_path, api_key):
    """Upload audio file to AssemblyAI"""
    headers = {'authorization': api_key}
    
    with open(file_path, 'rb') as f:
        response = requests.post(
            'https://api.assemblyai.com/v2/upload',
            headers=headers,
            files={'file': f}
        )
    
    if response.status_code == 200:
        return response.json()['upload_url']
    else:
        raise Exception(f"Upload failed: {response.status_code} - {response.text}")

def submit_transcription(audio_url, api_key, language_code=None):
    """Submit transcription request to AssemblyAI with language support"""
    headers = {
        'authorization': api_key,
        'content-type': 'application/json'
    }
    
    data = {
        'audio_url': audio_url,
        'language_detection': True,  # Enable automatic language detection
        'multichannel': False,
        'punctuate': True,
        'format_text': True,
    }
    
    # If specific language is provided, use it
    if language_code:
        data['language_code'] = language_code
        data['language_detection'] = False
    
    response = requests.post(
        'https://api.assemblyai.com/v2/transcript',
        headers=headers,
        json=data
    )
    
    if response.status_code == 200:
        return response.json()['id']
    else:
        raise Exception(f"Transcription submission failed: {response.status_code} - {response.text}")

def poll_transcription(transcript_id, api_key, job_id):
    """Poll AssemblyAI for transcription completion"""
    headers = {'authorization': api_key}
    
    while True:
        response = requests.get(
            f'https://api.assemblyai.com/v2/transcript/{transcript_id}',
            headers=headers
        )
        
        if response.status_code != 200:
            transcription_results[job_id] = {
                'status': 'error',
                'error': f"Polling failed: {response.status_code} - {response.text}"
            }
            return
        
        result = response.json()
        status = result['status']
        
        transcription_results[job_id] = {'status': status}
        
        if status == 'completed':
            # Generate MCQs after transcript is completed
            transcription_results[job_id] = {
                'status': 'generating_mcqs',
                'transcript': result['text'],
                'language_detected': result.get('language_detected'),
                'language_confidence': result.get('confidence', 0),
                'audio_duration': result.get('audio_duration')
            }
            
            # Generate MCQs using GroqCloud
            mcq_data = generate_mcqs_with_groq(
                result['text'], 
                result.get('language_detected', 'en')
            )
            
            # Update with final results
            transcription_results[job_id] = {
                'status': 'completed',
                'language_detected': result.get('language_detected'),
                'language_confidence': result.get('confidence', 0),
                'audio_duration': result.get('audio_duration'),
                'mcqs': mcq_data
            }
            return
        elif status == 'error':
            transcription_results[job_id] = {
                'status': 'error',
                'error': result.get('error', 'Unknown error')
            }
            return
        
        time.sleep(5)

def generate_mcqs_with_groq(transcript, language_detected="en"):
    """Generate MCQs using GroqCloud API based on the transcript"""
    
    # Language-specific prompts
    prompts = {
        "hi": f"""कृपया निम्नलिखित ट्रांसक्रिप्ट के आधार पर 5 बहुविकल्पीय प्रश्न बनाएं।
        
ट्रांसक्रिप्ट: {transcript}

कृपया निम्नलिखित JSON प्रारूप में उत्तर दें:
{{
    "mcqs": [
        {{
            "question": "प्रश्न यहाँ",
            "options": ["A) विकल्प 1", "B) विकल्प 2", "C) विकल्प 3", "D) विकल्प 4"],
            "correct_answer": "A",
            "explanation": "सही उत्तर का स्पष्टीकरण"
        }}
    ]
}}

सुनिश्चित करें कि प्रश्न ट्रांसक्रिप्ट की मुख्य सामग्री से संबंधित हैं।""",
        
        "ne": f"""कृपया निम्नलिखित ट्रान्सक्रिप्टको आधारमा ५ बहुविकल्पीय प्रश्नहरू बनाउनुहोस्।
        
ट्रान्सक्रिप्ट: {transcript}

कृपया निम्नलिखित JSON ढाँचामा जवाफ दिनुहोस्:
{{
    "mcqs": [
        {{
            "question": "प्रश्न यहाँ",
            "options": ["A) विकल्प १", "B) विकल्प २", "C) विकल्प ३", "D) विकल्प ४"],
            "correct_answer": "A",
            "explanation": "सही उत्तरको व्याख्या"
        }}
    ]
}}

प्रश्नहरू ट्रान्सक्रिप्टको मुख्य सामग्रीसँग सम्बन्धित छन् भन्ने कुरा सुनिश्चित गर्नुहोस्।""",
        
        "en": f"""Please create 5 multiple choice questions based on the following transcript.

Transcript: {transcript}

Please respond in the following JSON format:
{{
    "mcqs": [
        {{
            "question": "Question here",
            "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
            "correct_answer": "A",
            "explanation": "Explanation of the correct answer"
        }}
    ]
}}

Make sure the questions are relevant to the main content discussed in the transcript."""
    }
    
    # Use English prompt as default if language not supported
    prompt = prompts.get(language_detected, prompts["en"])
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "model": "llama3-8b-8192",
        "temperature": 0.7,
        "max_tokens": 2048
    }
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Try to parse JSON from the response
            import json
            try:
                # Find JSON in the response
                start = content.find('{')
                end = content.rfind('}') + 1
                if start != -1 and end != -1:
                    json_str = content[start:end]
                    mcq_data = json.loads(json_str)
                    return mcq_data
                else:
                    raise ValueError("No JSON found in response")
            except (json.JSONDecodeError, ValueError):
                # If JSON parsing fails, return a structured error
                return {
                    "error": "Failed to parse MCQ response",
                    "raw_response": content
                }
        else:
            return {
                "error": f"GroqCloud API error: {response.status_code} - {response.text}"
            }
    except Exception as e:
        return {
            "error": f"Failed to generate MCQs: {str(e)}"
        }

def cleanup_file(file_path):
    """Remove temporary audio file"""
    try:
        Path(file_path).unlink()
    except FileNotFoundError:
        pass

def process_transcription(youtube_url, job_id, language_code=None):
    """Background task to process transcription"""
    # Use tempfile to create a temporary file that is automatically cleaned up
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_audio_file:
        audio_file_path = temp_audio_file.name

    try:
        transcription_results[job_id] = {'status': 'downloading'}
        download_audio(youtube_url, audio_file_path)
        
        transcription_results[job_id] = {'status': 'uploading'}
        audio_url = upload_to_assemblyai(audio_file_path, ASSEMBLYAI_API_KEY)
        
        transcription_results[job_id] = {'status': 'submitting'}
        transcript_id = submit_transcription(audio_url, ASSEMBLYAI_API_KEY, language_code)
        
        transcription_results[job_id] = {'status': 'processing'}
        poll_transcription(transcript_id, ASSEMBLYAI_API_KEY, job_id)
        
    except Exception as e:
        transcription_results[job_id] = {
            'status': 'error',
            'error': str(e)
        }
    
    finally:
        cleanup_file(audio_file_path)


@app.route('/')
def index():
    return render_template('index.html')

# Healthcheck endpoint for Railway
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Railway"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'youtube-transcription'
    }), 200

@app.route('/transcribe', methods=['POST'])
def transcribe():
    data = request.get_json()
    youtube_url = data.get('url')
    language_code = data.get('language')  # Optional language selection
    
    if not youtube_url:
        return jsonify({'error': 'YouTube URL is required'}), 400
    
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    
    # Start background transcription process
    thread = threading.Thread(target=process_transcription, args=(youtube_url, job_id, language_code))
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id})

@app.route('/status/<job_id>')
def status(job_id):
    result = transcription_results.get(job_id, {'status': 'not_found'})
    return jsonify(result)