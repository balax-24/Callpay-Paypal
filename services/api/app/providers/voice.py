"""Voice + messaging provider chains.

STT:  Deepgram -> AssemblyAI -> OpenAI Whisper -> (browser Web Speech API on the client)
TTS:  ElevenLabs -> Cartesia -> OpenAI TTS -> (browser speechSynthesis on the client)
SMS:  Twilio -> Telnyx -> "screen" (link shown in the call widget / read aloud)

Phone calls themselves come in through Twilio or Telnyx webhooks (TwiML/TeXML, see routes_voice.py);
the browser WebRTC widget is the always-available last resort.
"""

import asyncio

import httpx

from ..config import Settings
from .chain import FallbackChain


class _Base:
    name = "base"
    key_attr = ""

    def __init__(self, s: Settings, http: httpx.AsyncClient):
        self.s, self.http = s, http

    def configured(self) -> bool:
        return bool(getattr(self.s, self.key_attr, ""))


# ---------------- speech to text ----------------
class Deepgram(_Base):
    name, key_attr = "deepgram", "deepgram_api_key"

    async def transcribe(self, audio: bytes, mime: str) -> str:
        r = await self.http.post(
            "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true",
            headers={"Authorization": f"Token {self.s.deepgram_api_key}", "Content-Type": mime},
            content=audio,
        )
        r.raise_for_status()
        return r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


class AssemblyAI(_Base):
    name, key_attr = "assemblyai", "assemblyai_api_key"

    async def transcribe(self, audio: bytes, mime: str) -> str:
        h = {"authorization": self.s.assemblyai_api_key}
        up = await self.http.post("https://api.assemblyai.com/v2/upload", headers=h, content=audio)
        up.raise_for_status()
        job = await self.http.post("https://api.assemblyai.com/v2/transcript", headers=h, json={"audio_url": up.json()["upload_url"]})
        job.raise_for_status()
        tid = job.json()["id"]
        for _ in range(40):
            await asyncio.sleep(0.5)
            r = await self.http.get(f"https://api.assemblyai.com/v2/transcript/{tid}", headers=h)
            d = r.json()
            if d["status"] == "completed":
                return d.get("text") or ""
            if d["status"] == "error":
                raise RuntimeError(d.get("error"))
        raise TimeoutError("assemblyai timeout")


class OpenAIWhisper(_Base):
    name, key_attr = "openai_whisper", "openai_api_key"

    async def transcribe(self, audio: bytes, mime: str) -> str:
        ext = "webm" if "webm" in mime else "wav" if "wav" in mime else "ogg" if "ogg" in mime else "mp3"
        r = await self.http.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.s.openai_api_key}"},
            files={"file": (f"audio.{ext}", audio, mime)},
            data={"model": "whisper-1"},
        )
        r.raise_for_status()
        return r.json()["text"]


# ---------------- text to speech ----------------
class ElevenLabs(_Base):
    name, key_attr = "elevenlabs", "elevenlabs_api_key"

    async def speak(self, text: str) -> tuple[bytes, str]:
        r = await self.http.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.s.elevenlabs_voice_id}?optimize_streaming_latency=3",
            headers={"xi-api-key": self.s.elevenlabs_api_key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": "eleven_flash_v2_5"},
        )
        r.raise_for_status()
        return r.content, "audio/mpeg"


class Cartesia(_Base):
    name, key_attr = "cartesia", "cartesia_api_key"

    async def speak(self, text: str) -> tuple[bytes, str]:
        r = await self.http.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={"X-API-Key": self.s.cartesia_api_key, "Cartesia-Version": "2024-06-10"},
            json={
                "model_id": "sonic-2", "transcript": text,
                "voice": {"mode": "id", "id": self.s.cartesia_voice_id},
                "output_format": {"container": "mp3", "bit_rate": 128000, "sample_rate": 44100},
            },
        )
        r.raise_for_status()
        return r.content, "audio/mpeg"


class OpenAITTS(_Base):
    name, key_attr = "openai_tts", "openai_api_key"

    async def speak(self, text: str) -> tuple[bytes, str]:
        r = await self.http.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {self.s.openai_api_key}"},
            json={"model": "gpt-4o-mini-tts", "voice": "alloy", "input": text, "response_format": "mp3"},
        )
        r.raise_for_status()
        return r.content, "audio/mpeg"


# ---------------- SMS ----------------
class TwilioSMS(_Base):
    name, key_attr = "twilio", "twilio_auth_token"

    def configured(self) -> bool:
        return bool(self.s.twilio_account_sid and self.s.twilio_auth_token and self.s.twilio_from_number)

    async def send(self, to: str, body: str) -> str:
        r = await self.http.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_account_sid}/Messages.json",
            auth=(self.s.twilio_account_sid, self.s.twilio_auth_token),
            data={"To": to, "From": self.s.twilio_from_number, "Body": body},
        )
        r.raise_for_status()
        return r.json()["sid"]


class TelnyxSMS(_Base):
    name, key_attr = "telnyx", "telnyx_api_key"

    def configured(self) -> bool:
        return bool(self.s.telnyx_api_key and self.s.telnyx_from_number)

    async def send(self, to: str, body: str) -> str:
        r = await self.http.post(
            "https://api.telnyx.com/v2/messages",
            headers={"Authorization": f"Bearer {self.s.telnyx_api_key}"},
            json={"from": self.s.telnyx_from_number, "to": to, "text": body},
        )
        r.raise_for_status()
        return r.json()["data"]["id"]


STT = {c.name: c for c in (Deepgram, AssemblyAI, OpenAIWhisper)}
TTS = {c.name: c for c in (ElevenLabs, Cartesia, OpenAITTS)}
SMS = {c.name: c for c in (TwilioSMS, TelnyxSMS)}


def _order(csv: str) -> list[str]:
    return [p.strip() for p in csv.split(",") if p.strip()]


def build_voice_chains(s: Settings, http: httpx.AsyncClient, on_failover=None) -> dict[str, FallbackChain]:
    return {
        "stt": FallbackChain("stt", [STT[n](s, http) for n in _order(s.providers_stt) if n in STT], timeout_s=15, on_failover=on_failover),
        "tts": FallbackChain("tts", [TTS[n](s, http) for n in _order(s.providers_tts) if n in TTS], timeout_s=10, on_failover=on_failover),
        "sms": FallbackChain("sms", [SMS[n](s, http) for n in _order(s.providers_sms) if n in SMS], timeout_s=10, on_failover=on_failover),
    }
