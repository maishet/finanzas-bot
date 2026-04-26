import os

from groq import Groq


class VoiceTranscriptionError(Exception):
    pass


def _get_client():
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise VoiceTranscriptionError(
            "No se encontró GROQ_API_KEY para transcripción de voz."
        )

    return Groq(api_key=api_key)


def transcribe_audio_file(file_path, language="es"):
    """Transcribe audio a texto. No guarda transcrito ni puntaje de confianza."""
    client = _get_client()
    model = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3").strip() or "whisper-large-v3"

    with open(file_path, "rb") as audio_file:
        result = client.audio.transcriptions.create(model=model, file=audio_file, language=language)

    text = (getattr(result, "text", "") or "").strip()
    if not text:
        raise VoiceTranscriptionError("No se pudo obtener texto de la nota de voz.")
    return text
