# PreNewBrain: Robert and Peter at home

A portable copy of the existing Robert and Peter Parker text-and-voice setup. The original Kira World files remain untouched.

Robert is the owner-authorized AI variant grounded in Robert McMurrer's supplied life story. Peter is the existing Peter Parker / Spider-Man **No Way Home Final Suit** variant. In conversation both use the immersive first-person style already requested, without routine AI/dataset/fictional disclaimers. Direct identity questions are answered honestly; neither is the biological owner or actual actor.

## Install and launch

Use a separate Python 3.11 environment:

~~~powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-voice.txt
~~~

Install [Ollama](https://ollama.com/) separately, then obtain the model selected by the original launcher:

~~~powershell
ollama pull qwen3.5:9b
~~~

Run **Start_Chat_Talk.bat**. It opens a desktop chat window, or the same local interface in your browser if pywebview is unavailable. Select Robert or Peter, type a message, and leave **Speak with Chatterbox** enabled to hear the reply. This package does not include microphone input or a 3D body.

The actual original default is Ollama **qwen3.5:9b**, digest **6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7**. The portable copy requests the configured tag; a fresh download is not automatically proven byte-identical to the old installed model. No text-model weights are bundled.

## The voices

Both exact reviewed WAV references are included and hash-checked before speech. Robert's reference is 36.57 seconds; Peter's is 28.83 seconds. They use the original English **chatterbox.tts.ChatterboxTTS** API with each person's reference supplied through audio_prompt_path. There is no generic OS-voice substitution.

Robert retains the original single-pass -9.5 dB gain, 95 Hz proximity correction and 0.3 mix. Peter's calibration remains zero/off. The copied speech chunking and signal-validation utilities retain their original source. A separate worker generates the whole reply and exits; the Ollama request releases model residency before speech.

The local environment evidence records Chatterbox **0.1.7** with Python **3.11.9**. Historical CPU/GPU lockfiles are provided under runtime-recipes as machine-specific installation provenance. The CPU environment used Torch/Torchaudio 2.6.0. Its RTX 5060 Ti GPU environment used 2.11.0+cu130, with expressly recorded legacy Chatterbox dependency conflicts. Those Kira sidecar records do not establish the exact historical global interpreter used for every Robert/Peter reply, or prove this portable copy on another computer.

Set voice_device to auto, cpu or cuda. To use an existing compatible Chatterbox environment, set voice_python in config.local.json to that environment's interpreter. A CPU run preserves the reference and calibration but changes latency. Python environments, CUDA libraries and Chatterbox model weights are installed separately. Initial Chatterbox loading may fetch its own model files; prepare its cache while online if later offline use is required.

See [Chatterbox installation/API documentation](https://github.com/resemble-ai/chatterbox) and its [model card](https://huggingface.co/ResembleAI/chatterbox). Library/model MIT licensing does not establish third-party reference-audio rights. The exact source and unresolved Peter distribution evidence are recorded in **VOICE_RIGHTS.md**.

## Use another local model

Copy **config.local.example.json** to **config.local.json**. For another Ollama model, change model to its installed tag and keep the Ollama endpoint.

An OpenAI-compatible local server can use:

~~~json
{
  "backend": "openai-compatible",
  "endpoint": "http://127.0.0.1:1234/v1/chat/completions",
  "model": "your-loaded-local-model",
  "voice_device": "auto"
}
~~~

Only loopback endpoints are accepted. No API keys or credentials are included. Different models can change conversation style, memory use, reliability and speed; they remain untested here. Qwen 3.5 requests disable thinking output. Switching the text model does not replace either voice reference.

## Robert's complete life context

The entire supplied autobiography and all **14** supplied autobiographical accounts are included. Contact/credential checks and any release redactions are recorded separately for review. His Los Angeles homelessness and other hardships are retained as his own source-backed life story, not removed merely because they are sensitive.

The complete documents are indexed in **91** nonoverlapping chunks. Local lexical retrieval supplies relevant passages to a reply without requiring a separate embedding model. Every source byte is covered; this is source coverage, not proof of perfect model recall. Robert may naturally say “when I was homeless in Los Angeles.” Missing details should sound natural, such as “I don't remember that detail,” and must not become invented facts.

Peter receives the existing variant metadata and limited source context. No missing interaction episodes were invented. The screenplay, mixed source video, avatar models, protected Maya material, original Kira runtime/state and unrelated private project memories are not bundled.

New conversations stay separately under runtime/history; generated speech and worker logs stay under runtime/audio. These folders and config.local.json are ignored by Git. Clearing a conversation affects only this copy.

## Current status and future NewBrain use

Demonstration/reference: [Peter Parker interview](https://youtu.be/vNRTwMvkR3g), supplied by the owner as his interview with the existing Peter variant. The page title is **I Interviewed a Synthetic Peter Parker After No Way Home | Kira World TemporaryAI Test**. The video/audio contents were not watched or verified during this packaging pass, and the link is not a new voice-redistribution license.

This is **pre-NewBrain**, using the existing local-model/profile approach. It contains no accepted NewBrain model or weights. Future NewBrain integration is experimental; no three-to-six-month delivery or capability promise is made.

Static source, JSON, path, reference-hash, complete-source coverage and persona checks are prepared. Desktop startup, model chat, speech generation, retrieval performance and perceptual voice comparison remain **UNRUN** until separately supervised. Exact WAV identity preserves the input reference; it does not guarantee identical new generations on different installations.
