"""Versioned live-practice protocol. Capture supports one-question and continuous question modes."""
from __future__ import annotations

import asyncio
import audioop
import base64
import hmac
import json
import os
import uuid
import time
from collections import deque
from .turns import question_candidate
from .speakers import SpeakerTimeline
from .models import account_models, resolve_model, AnswerModelError
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Header, HTTPException
from .providers import answer_stream, openai_transcription_session, transcription_diagnostic, align_candidate_speech
from .retrieval import search
from .storage import active_profile, chunks_for, core_profile_for, connect

router = APIRouter()

@router.get('/api/models')
async def list_answer_models(x_app_token: str | None = Header(None)):
    expected=os.getenv('APP_TOKEN','')
    if not expected or not isinstance(x_app_token,str) or not hmac.compare_digest(expected,x_app_token):
        raise HTTPException(status_code=401,detail='Invalid app access token')
    try:
        return {'models':await account_models(),'note':'Listed IDs are not proof of Responses API compatibility.'}
    except AnswerModelError as error:
        raise HTTPException(status_code=502,detail=str(error)) from None



@router.websocket('/ws/live')
async def live(ws: WebSocket):
    await ws.accept()
    stt = None
    reader = None
    generation = None
    listening = False
    rate_state = None
    history: list[str] = []
    endpoint = None
    segments = {}
    completed_items = set()
    speaking = False
    quiet_seconds = 2.0
    manual_finish = False
    last_question = ""
    output_language = "english"
    continuous = False
    submitted_items = deque(maxlen=256)
    timeline = SpeakerTimeline()
    frame_role = 'unknown'
    starts = {}
    ends = {}
    item_roles = {}
    speaker_gate = False
    voice_follow = False
    alignment = None
    current_answer = ''
    current_answer_id = ''
    answer_model = None
    answer_effort = "auto"
    coach_instructions = ""
    stt_started = 0.0

    def cancel_endpoint():
        nonlocal endpoint
        if endpoint and endpoint is not asyncio.current_task():
            endpoint.cancel()
        endpoint = None

    def question_text():
        return ' '.join(text for text in segments.values() if text).strip()

    async def finish_question(force=False):
        nonlocal listening, generation
        if not listening or speaking or any(k not in completed_items for k in segments):
            await send('state', message='Waiting for speech transcription to finish…')
            return
        question = question_text()
        if not question:
            await send('state', message='No question captured yet. Keep speaking.')
            return
        cancel_endpoint()
        if continuous:
            roles = {item_roles.get(k, 'unknown') for k in segments}
            submitted_items.extend(segments)
            segments.clear()
            completed_items.clear()
            if not force and ((speaker_gate and roles != {'interviewer'}) or (not speaker_gate and not question_candidate(question))):
                await send('state', message='Still listening. Speaker or question was not clear; last answer retained. Use manual Interviewer mode if needed.')
                return
        else:
            listening = False
            await send('capture', active=False)
        if generation and not generation.done():
            generation.cancel()
            with suppress(asyncio.CancelledError):
                await generation
        await send('transcript.final', text=question)
        generation = asyncio.create_task(generate(question))

    async def finish_after_quiet():
        try:
            await asyncio.sleep(quiet_seconds)
            await finish_question()
        except asyncio.CancelledError:
            pass

    def schedule_endpoint():
        nonlocal endpoint
        cancel_endpoint()
        if segments and not manual_finish and not speaking and all(k in completed_items for k in segments):
            endpoint = asyncio.create_task(finish_after_quiet())
    send_lock = asyncio.Lock()

    async def send(kind, **fields):
        async with send_lock:
            await ws.send_json({'type': kind, **fields})

    async def close_capture():
        nonlocal listening, stt, reader, rate_state
        listening = False
        cancel_endpoint()
        if reader and reader is not asyncio.current_task():
            reader.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await reader
        reader = None
        if stt:
            await stt.close()
            stt = None
        rate_state = None

    async def generate(question):
        nonlocal last_question, current_answer, current_answer_id
        last_question = question
        requested_model, requested_effort = answer_model, answer_effort
        selected_output_language = output_language
        selected_coach_instructions = coach_instructions
        request_started = time.monotonic()
        first_delta = True
        first_text_ms = None
        try:
            selected_answer_model, selected_effort = resolve_model(requested_model, requested_effort)
            with connect() as db:
                profile = active_profile(db)
                chunks = chunks_for(db, profile['id'], include_core=False) if profile else []
                core = core_profile_for(db, profile['id']) if profile else ''
                evidence = search(chunks, question)
                if not evidence:
                    evidence = chunks[:7]
            grounded = ('[USER-REPORTED CORE PROFILE; facts are not independently verified]\n'+core+'\n\n' if core else '')+'\n\n'.join(f'[{c.source}] {c.text}' for c in evidence)
            answer_id = uuid.uuid4().hex
            current_answer_id = answer_id
            current_answer = ''
            await send('answer.start', answer_id=answer_id, question=question, model=selected_answer_model, reasoning=selected_effort or 'API default')
            full = ''
            async for delta in answer_stream(question, grounded, '\n'.join(history[-12:])[-16000:], selected_output_language, selected_answer_model, selected_effort or "default", selected_coach_instructions):
                full += delta
                current_answer = full
                if first_delta:
                    first_delta = False
                    first_text_ms=round((time.monotonic()-request_started)*1000)
                    print('LIVE_ANSWER_FIRST_TEXT_MS',first_text_ms,flush=True)
                await send('answer.delta', answer_id=answer_id, text=delta, first_text_ms=first_text_ms)
            history.extend([f'user: {question}', f'assistant: {full}'])
            del history[:-12]
            await send('answer.done', answer_id=answer_id, text=full, first_text_ms=first_text_ms, total_ms=round((time.monotonic()-request_started)*1000))
        except asyncio.CancelledError:
            raise
        except AnswerModelError as error:
            await send('error', keep_capture=continuous and listening, message=str(error))
        except Exception:
            await send('error', keep_capture=continuous and listening, message='Answer failed. Use Retry last answer. Listening continues if the microphone indicator is on.')

    async def follow(spoken, answer, answer_id):
        try:
            quote = await align_candidate_speech(spoken, answer)
            if quote and voice_follow and answer_id == current_answer_id:
                await send('follow', answer_id=answer_id, quote=quote)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print('LIVE_ALIGNMENT_FAILED '+transcription_diagnostic(error),flush=True)
            await send('follow.state', message='Could not match speech. Holding the page; ring scrolling is available.')

    async def read_stt(connection):
        nonlocal listening, speaking, alignment
        try:
            async for raw in connection:
                event = json.loads(raw)
                kind = event.get('type', '')
                if kind in ('error', 'conversation.item.input_audio_transcription.failed'):
                    raise RuntimeError('Transcription failed')
                if not listening:
                    continue
                item = event.get('item_id', 'legacy')
                if continuous and item in submitted_items:
                    continue
                if kind == 'input_audio_buffer.speech_started':
                    cancel_endpoint()
                    speaking = True
                    segments.setdefault(item, '')
                    starts[item] = event.get('audio_start_ms', timeline.offset)
                elif kind == 'input_audio_buffer.speech_stopped':
                    speaking = False
                    ends[item] = event.get('audio_end_ms', timeline.offset)
                    item_roles[item] = timeline.role(starts.get(item),ends[item])
                    segments.setdefault(item, '')
                    schedule_endpoint()
                elif kind == 'input_audio_buffer.committed':
                    segments.setdefault(item, '')
                    cancel_endpoint()
                elif kind == 'conversation.item.input_audio_transcription.delta':
                    if item in completed_items:
                        continue
                    cancel_endpoint()
                    segments[item] = segments.get(item, '') + event.get('delta', '')
                    role = item_roles.get(item, timeline.role(starts.get(item),timeline.offset))
                    if role != 'candidate':
                        await send('transcript.partial', text=question_text())
                elif kind == 'conversation.item.input_audio_transcription.completed':
                    if item in completed_items:
                        continue
                    transcript = event.get('transcript', '').strip()
                    role = item_roles.get(item, timeline.role(starts.get(item),ends.get(item)))
                    if role == 'candidate':
                        segments.pop(item,None)
                        completed_items.discard(item)
                        submitted_items.append(item)
                        await send('candidate.transcript', text=transcript)
                        if voice_follow and current_answer:
                            if alignment:
                                alignment.cancel()
                            alignment = asyncio.create_task(follow(transcript,current_answer,current_answer_id))
                        schedule_endpoint()
                        continue
                    segments[item] = transcript
                    completed_items.add(item)
                    await send('transcript.partial', text=question_text())
                    schedule_endpoint()
                for mapping in (starts, ends, item_roles):
                    if len(mapping)>512:
                        for key in list(mapping):
                            if key not in segments:
                                mapping.pop(key,None)
                if len(question_text()) > 12000 or len(segments) > 100:
                    raise RuntimeError('Question capture limit exceeded')
            if listening:
                raise RuntimeError('Transcription disconnected')
        except asyncio.CancelledError:
            raise
        except Exception:
            listening = False
            cancel_endpoint()
            await send('capture', active=False)
            await send('error', recoverable=True, message='Transcription stopped or question exceeded the capture limit. Captured text is retained; tap Next question to retry.')
        finally:
            await connection.close()

    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
        expected = os.getenv('APP_TOKEN', '')
        supplied = hello.get('token', '')
        if not expected or not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
            await ws.close(code=1008, reason='Invalid app access token')
            return
        if hello.get('type') != 'auth':
            await ws.close(code=1008, reason='Authentication required')
            return
        await send('ready', protocol=1, build='0.2.7', features=['continuous_questions','preparation','display_settings','speaker_follow','model_selection','all_models','coach_instructions','core_profile'])
        while True:
            event = await ws.receive()
            if event['type'] == 'websocket.disconnect':
                break
            audio = event.get('bytes')
            if audio is not None:
                if len(audio) > 64000 or len(audio) % 2:
                    await ws.close(code=1009, reason='Invalid PCM frame')
                    break
                if listening and stt and audio:
                    timeline.append(len(audio), frame_role)
                    pcm, rate_state = audioop.ratecv(audio, 2, 1, 16000, 24000, rate_state)
                    await stt.send(json.dumps({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode('ascii')}))
                continue
            raw = event.get('text', '')
            if len(raw) > 8192:
                await ws.close(code=1009)
                break
            message = json.loads(raw)
            kind = message.get('type')
            if kind == 'coach.instructions':
                text = message.get('text','')
                if not isinstance(text,str) or len(text)>4000:
                    await send('state',message='Coach instructions must be text of 4,000 characters or fewer.')
                    continue
                coach_instructions = text.strip()
                await send('coach.instructions.saved', active=bool(coach_instructions), characters=len(coach_instructions))
                continue
            if kind == 'speaker':
                role = message.get('role')
                frame_role = role if role in ('candidate','interviewer') else 'unknown'
                continue
            if kind == 'follow.mode':
                voice_follow = message.get('enabled') is True
                if not voice_follow and alignment:
                    alignment.cancel()
                continue
            if kind in ('listen', 'retry', 'settings'):
                selected_model = message.get('model') or None
                selected_effort = message.get('reasoning_effort','auto')
                try:
                    resolve_model(selected_model,selected_effort)
                except ValueError as error:
                    await send('state',message=str(error))
                    continue
                selected_language = message.get('output_language', 'english')
                if selected_language not in ('english', 'telugu_latin'):
                    await send('state', message='Choose English or Romanized Telugu for lens answers.')
                    continue
                if kind == 'settings' or (not speaking and not (generation and not generation.done())):
                    output_language = selected_language
                    answer_model = selected_model
                    answer_effort = selected_effort
                if kind == 'settings':
                    await send('state',message='Model and language saved for the next answer; microphone unchanged.')
                    continue
            if kind == 'ping':
                await send('pong')
                if continuous and listening and not speaking and not segments and time.monotonic()-stt_started>2700:
                    await send('state',message='Renewing transcription session; a brief capture gap is possible.')
                    await close_capture()
                    await send('capture',active=False)
                    try:
                        timeline = SpeakerTimeline()
                        starts.clear(); ends.clear(); item_roles.clear(); submitted_items.clear()
                        stt = await openai_transcription_session()
                        stt_started = time.monotonic()
                        listening = True
                        reader = asyncio.create_task(read_stt(stt))
                        await send('capture',active=True)
                    except Exception as error:
                        print('LIVE_RENEWAL_FAILED '+transcription_diagnostic(error),flush=True)
                        await send('error',recoverable=True,message='Session renewal failed. Reconnecting transcription.')
            elif kind == 'retry':
                if (listening and (not continuous or speaking or segments)) or (generation and not generation.done()):
                    await send('state', message='Finish or pause capture and wait for the current answer before retrying.')
                elif last_question:
                    if len(history) >= 2 and history[-2] == f'user: {last_question}':
                        del history[-2:]
                    generation = asyncio.create_task(generate(last_question))
                else:
                    await send('state', message='No question in this connection yet. Choose Listen and repeat your question.')
            elif kind == 'finish':
                await finish_question(force=True)
            elif kind == 'pause':
                await close_capture()
                await send('capture', active=False)
            elif kind == 'listen':
                if generation and not generation.done() and message.get('continuous') is not True:
                    await send('state', message='Finishing the current answer')
                    continue
                await close_capture()
                try:
                    segments.clear()
                    completed_items.clear()
                    speaking = False
                    manual_finish = message.get('manual_finish') is True
                    continuous = message.get('continuous') is True and not manual_finish
                    speaker_gate = message.get('speaker_gate') is True
                    voice_follow = message.get('voice_follow') is True
                    timeline = SpeakerTimeline()
                    starts.clear(); ends.clear(); item_roles.clear()
                    submitted_items.clear()
                    stt = await openai_transcription_session()
                    stt_started = time.monotonic()
                    listening = True
                    reader = asyncio.create_task(read_stt(stt))
                    await send('capture', active=True)
                except Exception as error:
                    details = transcription_diagnostic(error)
                    print('LIVE_TRANSCRIPTION_START_FAILED ' + details, flush=True)
                    await close_capture()
                    await send('error', message='Could not start transcription: ' + details)
    except (WebSocketDisconnect, asyncio.TimeoutError) as error:
        print('LIVE_CONNECTION_ENDED ' + transcription_diagnostic(error), flush=True)
    except Exception as error:
        print('LIVE_CONNECTION_FAILED ' + transcription_diagnostic(error), flush=True)
        with suppress(Exception):
            await send('error', message='Live connection failed. Stop and start practice again.')
    finally:
        with suppress(Exception):
            await close_capture()
        if alignment:
            alignment.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await alignment
        if generation:
            generation.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await generation
        with suppress(Exception):
            await ws.close()
