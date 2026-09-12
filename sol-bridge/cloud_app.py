"""Single-user WSGI adapter, served by one Gunicorn worker on Render."""
import base64
import hmac
import json
import os
import time
import uuid
import urllib.error
from http import HTTPStatus
from pathlib import Path
import bridge

if os.environ.get('CANDIDATE_PROFILE_B64'):
    profile = Path('/tmp/even-ai-experience.md')
    profile.write_bytes(base64.b64decode(os.environ['CANDIDATE_PROFILE_B64'], validate=True))
    profile.chmod(0o600)
    bridge.EXPERIENCE = profile
credentials = bridge.load_secrets()
model = os.environ.get('OPENAI_MODEL', 'gpt-5.6-sol')
if model not in ('gpt-5.6-sol', 'gpt-6-astra', 'gpt-5.6-terra'):
    raise RuntimeError('Unsupported model configuration')
conversation = bridge.Conversation()

def app(environ, start_response):
    def reply(status, data):
        raw = json.dumps(data).encode()
        start_response(f'{status} {HTTPStatus(status).phrase}', [('Content-Type','application/json'),('Content-Length',str(len(raw))),('Cache-Control','no-store')])
        return [raw]
    path = environ.get('PATH_INFO')
    if path == '/health' and environ.get('REQUEST_METHOD') == 'GET':
        return reply(200, {'status':'ready','model':model,'profile_loaded':bridge.EXPERIENCE.exists(),'version':'2026-09-12-bullets-v2'})
    if path != '/v1/chat/completions': return reply(404, {'error':'Not found'})
    if environ.get('REQUEST_METHOD') != 'POST': return reply(405, {'error':'POST required'})
    if not hmac.compare_digest(environ.get('HTTP_AUTHORIZATION',''), 'Bearer '+credentials['bridge_token']):
        return reply(401, {'error':'Invalid bridge token'})
    try:
        size = int(environ.get('CONTENT_LENGTH') or '0')
        if not 0 < size <= 65536: return reply(413, {'error':'Invalid request size'})
        body = json.loads(environ['wsgi.input'].read(size))
        question = next((m.get('content') for m in reversed(body.get('messages',[])) if m.get('role')=='user'),None)
        if not isinstance(question,str) or not question.strip() or len(question)>12000:
            return reply(400, {'error':'A text question is required'})
    except (ValueError,TypeError,AttributeError): return reply(400, {'error':'Invalid request format'})
    try:
        answer, metrics = conversation.ask(question.strip(),model,credentials['api_key'])
        print(json.dumps({'time':int(time.time()),'model':model,**metrics}),flush=True)
    except urllib.error.HTTPError as error:
        answer = f'OpenAI request failed with HTTP {error.code}. Check API access and billing.'
    except Exception as error:
        print('Upstream failure: '+type(error).__name__,flush=True)
        answer = 'The model did not respond in time. Please try again.'
    return reply(200, {'id':'chatcmpl-'+uuid.uuid4().hex,'object':'chat.completion','created':int(time.time()),'model':model,'choices':[{'index':0,'message':{'role':'assistant','content':answer},'finish_reason':'stop'}]})
