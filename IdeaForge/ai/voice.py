from __future__ import annotations
import json, queue, tempfile, time, wave
from pathlib import Path
import numpy as np
import pyttsx3
import sounddevice as sd
from faster_whisper import WhisperModel

class FemaleVoice:
    def __init__(self,cfg):
        self.cfg=cfg
        self.engine=pyttsx3.init()
        self.engine.setProperty("rate",int(cfg.get("rate",180)))
        self.engine.setProperty("volume",float(cfg.get("volume",1.0)))
        self.selected_voice=None
        self._select_voice()

    def _select_voice(self):
        voices=self.engine.getProperty("voices") or []
        prefs=[x.lower() for x in self.cfg.get("preferred_names",[])]
        for pref in prefs:
            for v in voices:
                text=(getattr(v,"name","")+" "+getattr(v,"id","")).lower()
                if pref in text:
                    self.engine.setProperty("voice",v.id)
                    self.selected_voice=getattr(v,"name",v.id)
                    return
        if voices:
            self.selected_voice=getattr(voices[0],"name",voices[0].id)

    def speak(self,text):
        self.engine.say(text)
        self.engine.runAndWait()

class SpeechRecognizer:
    def __init__(self,cfg):
        self.cfg=cfg
        self.rate=int(cfg.get("sample_rate",16000))
        self.model=None

    def _model(self):
        if self.model is None:
            name=self.cfg.get("model","small.en")
            try:
                self.model=WhisperModel(name,device="cuda",compute_type="float16")
            except Exception:
                self.model=WhisperModel(name,device="cpu",compute_type="int8")
        return self.model

    def record_utterance(self,stop_event=None):
        threshold=float(self.cfg.get("speech_threshold",0.015))
        start_timeout=float(self.cfg.get("start_timeout_seconds",20))
        silence_target=float(self.cfg.get("silence_seconds",1.15))
        max_seconds=float(self.cfg.get("max_utterance_seconds",35))
        block=1024
        q=queue.Queue()
        def callback(indata,frames,time_info,status):
            q.put(indata.copy())
        chunks=[]
        started=False
        silent_for=0.0
        start=time.monotonic()
        with sd.InputStream(samplerate=self.rate,channels=1,dtype="float32",blocksize=block,callback=callback):
            while True:
                if stop_event is not None and stop_event.is_set():
                    return None
                if time.monotonic()-start > (max_seconds if started else start_timeout):
                    break
                try:
                    chunk=q.get(timeout=0.25)
                except queue.Empty:
                    continue
                level=float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
                if not started:
                    if level>=threshold:
                        started=True
                        chunks.append(chunk)
                    continue
                chunks.append(chunk)
                if level<threshold:
                    silent_for += len(chunk)/self.rate
                    if silent_for>=silence_target:
                        break
                else:
                    silent_for=0.0
        if not chunks:
            return None
        audio=np.concatenate(chunks,axis=0)
        pcm=np.clip(audio[:,0]*32767,-32768,32767).astype(np.int16)
        Path("temp_audio").mkdir(exist_ok=True)
        temp=Path("temp_audio")/"utterance.wav"
        with wave.open(str(temp),"wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.rate); w.writeframes(pcm.tobytes())
        return temp

    def transcribe(self,path):
        segments,_=self._model().transcribe(
            str(path),
            language=self.cfg.get("language","en"),
            vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()
