"""Manual G2 microphone capture. Uses the existing bridge credentials and profile."""
import io
import json
import hmac
import mimetypes
import os
import threading
import urllib.request
import urllib.error
import uuid
import wave
import time
import ring_agent
from pathlib import Path

ROOT = Path(__file__).parent / 'ring-ui'
_busy = threading.Lock()

def wav_file(pcm):
    if not 6400 <= len(pcm) <= 2880000 or len(pcm) % 2:
        raise ValueError('Invalid PCM length')
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
        writer.writeframes(pcm)
    return output.getvalue()

def transcribe(pcm, key):
    boundary = 'ringask' + uuid.uuid4().hex
    model = os.environ.get('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe')
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
               f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="question.wav"\r\n'
               'Content-Type: audio/wav\r\n\r\n').encode() + wav_file(pcm) + f'\r\n--{boundary}--\r\n'.encode()
    request = urllib.request.Request('https://api.openai.com/v1/audio/transcriptions', data=payload,
        headers={'Authorization':'Bearer '+key, 'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request, timeout=35) as response:
        result = json.load(response)
    text = result.get('text', '').strip()
    if not text: raise ValueError('No speech detected. Please try again.')
    return text

def handle(environ, start_response, credentials, conversation, model):
    path = environ.get('PATH_INFO', '')
    method = environ.get('REQUEST_METHOD', 'GET')
    cors = [('Access-Control-Allow-Origin','*'),('Access-Control-Allow-Headers','Authorization, Content-Type, X-Answer-Style'),
            ('Access-Control-Allow-Methods','GET, POST, OPTIONS'),('Cache-Control','no-store')]
    def reply(status, data):
        raw = json.dumps(data).encode()
        start_response(status, cors + [('Content-Type','application/json'),('Content-Length',str(len(raw)))])
        return [raw]
    if path.startswith('/ring/'):
        if method != 'GET': return reply('405 Method Not Allowed', {'error':'GET required'})
        relative = path[len('/ring/'):] or 'index.html'
        file = (ROOT / relative).resolve()
        if ROOT.resolve() not in file.parents or not file.is_file(): return reply('404 Not Found', {'error':'Not found'})
        raw = file.read_bytes()
        start_response('200 OK', [('Content-Type',mimetypes.guess_type(str(file))[0] or 'application/octet-stream'),('Content-Length',str(len(raw))),('Cache-Control','no-cache')])
        return [raw]
    if not path.startswith('/api/'): return None
    if method == 'OPTIONS':
        start_response('204 No Content', cors); return [b'']
    if not hmac.compare_digest(environ.get('HTTP_AUTHORIZATION',''),'Bearer '+credentials['bridge_token']):
        return reply('401 Unauthorized', {'error':'Enter the bridge token already used by your Even AI agent.'})
    if path == '/api/health' and method == 'GET':
        return reply('200 OK', {'configured': bool(credentials.get('api_key')), 'model':model, 'profile_loaded':ring_agent.bridge.EXPERIENCE.exists(), 'version':'0.2.2'})
    if path != '/api/ask': return reply('404 Not Found', {'error':'Not found'})
    if method != 'POST': return reply('405 Method Not Allowed', {'error':'POST required'})
    if environ.get('CONTENT_TYPE','').split(';')[0] != 'application/octet-stream':
        return reply('415 Unsupported Media Type', {'error':'Expected PCM audio.'})
    try:
        size = int(environ.get('CONTENT_LENGTH','0'))
        if not 6400 <= size <= 2880000 or size % 2: raise ValueError()
    except (TypeError,ValueError): return reply('400 Bad Request', {'error':'Record between 0.2 and 90 seconds.'})
    try:
        pcm = environ['wsgi.input'].read(size)
        if len(pcm) != size: raise ValueError('Incomplete audio')
    except Exception:
        return reply('400 Bad Request', {'error':'Incomplete audio. Try again.'})
    def events():
        if not _busy.acquire(blocking=False):
            yield from reply('429 Too Many Requests', {'error':'A question is already processing.'})
            return
        def event(kind, **values): return (json.dumps({'type':kind, **values})+'\n').encode()
        try:
            start_response('200 OK', cors + [('Content-Type','application/x-ndjson'),('X-Accel-Buffering','no')])
            start=time.perf_counter()
            yield event('status', text='Transcribing question…')
            question = transcribe(pcm, credentials['api_key'])
            yield event('transcript', text=question, transcriptionMs=round((time.perf_counter()-start)*1000))
            style=environ.get('HTTP_X_ANSWER_STYLE','natural')
            for item in ring_agent.conversation.stream(question, model, credentials['api_key'], style):
                yield (json.dumps(item)+'\n').encode()
        except urllib.error.HTTPError as error:
            yield event('error', text='OpenAI request failed (HTTP %s). Check API access and billing.' % error.code)
        except Exception:
            yield event('error', text='Could not complete the answer. Check the connection and try again.')
        finally:
            _busy.release()
    return events()
