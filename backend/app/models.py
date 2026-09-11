"""OpenAI answer-model selection. A model listing does not prove endpoint support."""
import json
import os
import re
from pathlib import Path
import httpx

CATALOG=json.loads(Path(__file__).with_name('model_catalog.json').read_text())
EFFORTS=('auto','default','none','minimal','low','medium','high','xhigh','max')

class AnswerModelError(RuntimeError):
    """Only locally authored, non-sensitive messages may be exposed to the phone."""


def valid_model_id(model):
    return isinstance(model,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}',model) is not None


def answer_candidate(model):
    return valid_model_id(model) and not re.search(r'(^|[-_:])(image|audio|realtime|live|transcribe|transcription|translate|whisper|tts|embedding|moderation|sora|dall)([-_:]|$)',model.lower())


def model_entry(model):
    return next((entry for entry in CATALOG if entry['id']==model),None)


def resolve_model(model=None,effort='auto'):
    model=model or os.getenv('OPENAI_MODEL','gpt-5-mini')
    if not valid_model_id(model):
        raise ValueError('Enter a valid OpenAI model ID, not a URL.')
    if not answer_candidate(model):
        raise ValueError('This model needs an audio, image or other specialized integration. Choose a text answer model.')
    if not isinstance(effort,str) or effort not in EFFORTS:
        raise ValueError('Unsupported reasoning effort.')
    entry=model_entry(model)
    resolved=(entry['auto'] if entry else None) if effort=='auto' else None if effort=='default' else effort
    if entry and resolved is not None and resolved not in entry['efforts']:
        raise ValueError('That reasoning effort is not supported by the selected model.')
    return model,resolved


def generation_budget(model,effort):
    if effort in ('xhigh','max'):return 32768
    if effort in ('medium','high'):return 16384
    return 8192 if effort or model.startswith(('gpt-5','gpt-6','o1','o3','o4','ft:')) else 1600


async def account_models():
    key=os.getenv('OPENAI_API_KEY')
    if not key:raise AnswerModelError('OPENAI_API_KEY is missing on Render.')
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.get('https://api.openai.com/v1/models',headers={'Authorization':'Bearer '+key})
        if response.status_code>=400:
            raise AnswerModelError(f'OpenAI model list failed (HTTP {response.status_code}). Check API key permissions and project access.')
        data=response.json()
        ids=sorted({row['id'] for row in data.get('data',[]) if isinstance(row,dict) and valid_model_id(row.get('id'))})
        return [{'id':model,'selectable':answer_candidate(model),'preset':model_entry(model) is not None} for model in ids]
    except AnswerModelError:raise
    except Exception:
        raise AnswerModelError('Could not load OpenAI models. Check the connection or try a preset/custom ID.') from None
