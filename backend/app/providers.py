async def openai_transcription_session():
    key = os.environ["OPENAI_API_KEY"]

    url = "wss://api.openai.com/v1/realtime?model=gpt-realtime"

    ws = await websockets.connect(
        url,
        additional_headers={
            "Authorization": f"Bearer {key}"
        },
        ping_interval=10,
        ping_timeout=10,
    )

    await ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {
                                "type": "audio/pcm",
                                "rate": 24000
                            },
                            "noise_reduction": {
                                "type": "far_field"
                            },
                            "transcription": {
                                "model": "gpt-live-transcribe",
                                "languages": ["en"],
                                "delay": "low",
                                "prompt": (
                                    "A professional job interview. "
                                    "Preserve technical product names, "
                                    "metrics, acronyms, and company names."
                                )
                            }
                        }
                    }
                }
            }
        )
    )

    return ws
