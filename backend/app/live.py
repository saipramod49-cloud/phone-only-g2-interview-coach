"""Versioned live-practice protocol. Capture is explicitly armed for each question."""
from __future__ import annotations

import asyncio
import audioop
import base64
import hmac
import json
import os
import uuid
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .providers import answer_stream, openai_transcription_session
from .retrieval import search
from .storage import active_profile, chunks_for, connect

router = APIRouter()


@router.websocket('/ws/live')
async def live(ws: WebSocket):
    await ws.accept()
    stt = None
    reader = None
    generation = None
    listening = False
    rate_state = None
    history: list[str] = []
    send_lock = asyncio.Lock()

    async def send(kind, **fields):
        async with send_lock:
            await ws.send_json({'type': kind, **fields})

    async def close_capture():
        nonlocal listening, stt, reader, rate_state
        listening = False
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
        try:
            with connect() as db:
                profile = active_profile(db)
                evidence = search(chunks_for(db, profile['id']), question) if profile else []
            grounded = '\n\n'.join(f'[{c.source}] {c.text}' for c in evidence)
            answer_id = uuid.uuid4().hex
            await send('answer.start', answer_id=answer_id, question=question)
            full = ''
            async for delta in answer_stream(question, grounded, '\n'.join(history[-12:])[-16000:]):
                full += delta
                await send('answer.delta', answer_id=answer_id, text=delta)
            history.extend([f'user: {question}', f'assistant: {full}'])
            del history[:-12]
            await send('answer.done', answer_id=answer_id, text=full)
        except asyncio.CancelledError:
            raise
        except Exception:
            await send('error', message='Answer failed. Check the Render logs and OpenAI configuration; tap Next question to retry.')

    async def read_stt(connection):
        nonlocal listening, generation
        partial = ''
        try:
            async for raw in connection:
                event = json.loads(raw)
                kind = event.get('type', '')
                if kind in ('error', 'conversation.item.input_audio_transcription.failed'):
                    raise RuntimeError('Transcription failed')
                if not listening:
                    continue
                if kind == 'conversation.item.input_audio_transcription.delta':
                    partial = (partial + event.get('delta', ''))[-4000:]
                    await send('transcript.partial', text=partial)
                elif kind == 'conversation.item.input_audio_transcription.completed':
                    question = event.get('transcript', '').strip()[:4000]
                    if not question:
                        partial = ''
                        continue
                    listening = False
                    await send('capture', active=False)
                    await send('transcript.final', text=question)
                    generation = asyncio.create_task(generate(question))
                    return
            raise RuntimeError('Transcription disconnected')
        except asyncio.CancelledError:
            raise
        except Exception:
            listening = False
            await send('capture', active=False)
            await send('error', message='Transcription stopped. Check OpenAI access and tap Next question to retry.')
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
        await send('ready', protocol=1)
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
                    pcm, rate_state = audioop.ratecv(audio, 2, 1, 16000, 24000, rate_state)
                    await stt.send(json.dumps({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode('ascii')}))
                continue
            raw = event.get('text', '')
            if len(raw) > 8192:
                await ws.close(code=1009)
                break
            message = json.loads(raw)
            kind = message.get('type')
            if kind == 'ping':
                await send('pong')
            elif kind == 'pause':
                await close_capture()
                await send('capture', active=False)
            elif kind == 'listen':
                if generation and not generation.done():
                    await send('state', message='Finishing the current answer')
                    continue
                await close_capture()
                try:
                    stt = await openai_transcription_session()
                    listening = True
                    reader = asyncio.create_task(read_stt(stt))
                    await send('capture', active=True)
                except Exception:
                    await close_capture()
                    await send('error', message='Could not start transcription. Check OPENAI_API_KEY and model access in Render.')
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        with suppress(Exception):
            await send('error', message='Live connection failed. Stop and start practice again.')
    finally:
        with suppress(Exception):
            await close_capture()
        if generation:
            generation.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await generation
        with suppress(Exception):
            await ws.close()
