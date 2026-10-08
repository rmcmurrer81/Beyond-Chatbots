using System;
using System.Collections.Generic;
using System.Globalization;
using System.Speech.Recognition;
using System.Speech.Synthesis;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

public sealed class KiraWindowsSpeech : IDisposable {
    const int MaxText = 4000, MaxLine = 32768;
    const string MutexName = @"Local\KiraHandsFreeSpeech.v1";
    readonly object sync = new object();
    readonly Queue<Action> signals = new Queue<Action>();
    readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = MaxLine };
    readonly Mutex lease = new Mutex(false, MutexName);
    RecognizerInfo info;
    SpeechRecognitionEngine recognizer;
    SpeechSynthesizer synth;
    dynamic sapi;
    Prompt prompt;
    string culture, voice, engine, reason = "", pendingText, state = "off";
    long session;
    long recognitionSession, promptSession;
    long recognitionCompletedSession = -1, speechCompletedSession = -1;
    bool stt, tts, ownsLease, wanted, paused, closing, speaking;
    bool recognitionCancel, speechCancel;
    bool queueOverflow;
    bool statePending;
    long stateSession = -1;

    static string Text(Dictionary<string,object> d, string k, string fallback) {
        object v; return d.TryGetValue(k, out v) && v is string ? (string)v : fallback;
    }
    static long Session(Dictionary<string,object> d) {
        object v;
        if (!d.TryGetValue("session", out v) || !(v is int || v is long)) throw new ArgumentException();
        return Convert.ToInt64(v);
    }
    Dictionary<string,object> Event(string type) {
        return new Dictionary<string,object> { {"type",type}, {"session",session} };
    }
    void Emit(Dictionary<string,object> e) {
        Console.WriteLine(json.Serialize(e)); Console.Out.Flush();
    }
    void Error(string code, bool fatal) {
        var e = Event("error"); e["code"] = code; e["fatal"] = fatal; Emit(e);
        if (fatal) { lock(sync) { wanted = false; paused = true; pendingText = null; } }
    }
    void State(string next, bool pending) {
        if(state==next && statePending==pending && stateSession==session) return;
        state = next;
        statePending=pending; stateSession=session;
        var e = Event("state"); e["state"] = next; e["pending_stop"] = pending;
        e["recognition_completed_session"]=recognitionCompletedSession;
        e["speech_completed_session"]=speechCompletedSession; Emit(e);
    }
    void Capability() {
        var e = Event("capabilities");
        e["stt_available"] = stt; e["tts_available"] = tts;
        e["voice_name"] = voice ?? ""; e["culture"] = culture;
        e["engine"] = engine; e["reason"] = reason; Emit(e);
    }
    void Signal(Action a) {
        lock(sync) { if (signals.Count < 32) signals.Enqueue(a); else queueOverflow = true; }
    }
    public KiraWindowsSpeech(Dictionary<string,object> config) {
        culture = Text(config,"culture","en-US");
        engine = Text(config,"tts_backend","system_speech");
        string selected = Text(config,"voice_name","");
        if (culture.Length > 64 || selected.Length > 128) throw new ArgumentException();
        try {
            var ci = CultureInfo.GetCultureInfo(culture);
            foreach (var r in SpeechRecognitionEngine.InstalledRecognizers())
                if (r.Culture.Name.Equals(ci.Name,StringComparison.OrdinalIgnoreCase)) { info = r; break; }
            stt = info != null;
            if (!stt) reason = "recognizer_unavailable";
        } catch { reason = "recognizer_unavailable"; }
        try {
            if (engine == "system_speech") {
                synth = new SpeechSynthesizer();
                foreach (var v in synth.GetInstalledVoices()) {
                    var vi = v.VoiceInfo;
                    if (v.Enabled && vi.Gender == VoiceGender.Female &&
                        vi.Culture.Name.Equals(culture,StringComparison.OrdinalIgnoreCase) &&
                        (selected.Length == 0 || vi.Name == selected)) {
                        if (voice == null || vi.Name == "Microsoft Zira Desktop") voice = vi.Name;
                    }
                }
                if (voice != null) { synth.SelectVoice(voice); synth.Rate=-1; synth.Volume=90; tts=true; }
                synth.SpeakCompleted += (s,e) => Signal(() => {
                    if (!Object.ReferenceEquals(prompt,e.Prompt)) return;
                    speechCompletedSession=promptSession;
                    prompt=null; speaking=false; speechCancel=false;
                    if (e.Error != null) Error("speech_failed",false);
                });
            } else if (engine == "sapi_com") {
                var type = Type.GetTypeFromProgID("SAPI.SpVoice");
                if (type == null) throw new InvalidOperationException();
                sapi = Activator.CreateInstance(type);
                dynamic tokens = sapi.GetVoices();
                string language = CultureInfo.GetCultureInfo(culture).LCID.ToString("X");
                for(int i=0;i<(int)tokens.Count;i++) {
                    dynamic token = tokens.Item(i);
                    string name = (string)token.GetDescription();
                    string gender = (string)token.GetAttribute("Gender");
                    string langs = (string)token.GetAttribute("Language");
                    bool matches = false;
                    foreach(string code in langs.Split(';'))
                        if(code.Equals(language,StringComparison.OrdinalIgnoreCase)) matches=true;
                    if(gender.Equals("Female",StringComparison.OrdinalIgnoreCase) && matches &&
                       (selected.Length==0 || selected==name)) {
                        sapi.Voice=token; voice=name; tts=true; break;
                    }
                }
                sapi.Rate=-1; sapi.Volume=90;
            } else { reason = "unsupported_tts_engine"; }
            if (!tts && reason.Length==0) reason="female_voice_unavailable";
        } catch { tts=false; if(reason.Length==0) reason="female_voice_unavailable"; }
    }
    bool Acquire() {
        if(ownsLease) return true;
        try { ownsLease=lease.WaitOne(0); }
        catch(AbandonedMutexException) { ownsLease=true; }
        if(!ownsLease) { Error("speech_busy_other_app",true); State("off",false); }
        return ownsLease;
    }
    void BeginRecognition() {
        SpeechRecognitionEngine r = null;
        try {
            r = new SpeechRecognitionEngine(info);
            r.LoadGrammar(new DictationGrammar());
            long generation = session;
            recognitionSession=generation;
            r.SpeechRecognized += (s,e) => {
                lock(sync) {
                    if(!wanted || paused || closing || session!=generation ||
                       !Object.ReferenceEquals(recognizer,r)) return;
                    paused=true; // one final utterance; never hear the app reply.
                }
                string text=e.Result.Text ?? "";
                bool cut=text.Length>MaxText;
                if(cut) text=text.Substring(0,MaxText);
                double confidence=e.Result.Confidence;
                Signal(() => {
                    if(session!=generation || !wanted || closing) return;
                    var row=Event("transcript"); row["text"]=text; row["confidence"]=confidence;
                    row["final"]=true; row["truncated"]=cut; Emit(row); State("thinking",false);
                });
            };
            r.RecognizeCompleted += (s,e) => Signal(() => {
                if(!Object.ReferenceEquals(recognizer,r)) return;
                r.Dispose(); recognitionCompletedSession=generation;
                recognizer=null; recognitionCancel=false;
                if(e.Error!=null) Error("recognizer_failed",true);
            });
            recognizer=r;
            r.SetInputToDefaultAudioDevice(); // only after a user start command.
            r.RecognizeAsync(RecognizeMode.Multiple);
            State("listening",false);
        } catch {
            if(r!=null) r.Dispose();
            recognizer=null; recognitionCancel=false;
            Error("microphone_unavailable",true); State("off",false);
        }
    }
    void CancelRecognition() {
        if(recognizer==null || recognitionCancel) return;
        recognitionCancel=true;
        try { recognizer.RecognizeAsyncCancel(); }
        catch { Error("recognizer_cancel_failed",true); }
    }
    void CancelSpeech() {
        if(!speaking || speechCancel) return;
        speechCancel=true;
        try {
            if(synth!=null) synth.SpeakAsyncCancelAll();
            else if(sapi!=null) sapi.Speak("",3); // async + purge queued speech.
        } catch { Error("speech_cancel_failed",true); }
    }
    void BeginSpeech(string text) {
        promptSession=session;
        speaking=true; speechCancel=false;
        State("speaking",false);
        try {
            if(synth!=null) {
                synth.SetOutputToDefaultAudioDevice();
                prompt=synth.SpeakAsync(text);
            } else { sapi.Speak(text,1); }
        } catch {
            speaking=false; prompt=null;
            Error("speech_failed",false);
        }
    }
    public void Command(Dictionary<string,object> d) {
        long incoming=Session(d);
        if(incoming<session) return;
        session=incoming;
        string command=Text(d,"command","");
        switch(command) {
        case "start":
            if(closing) return;
            Capability();
            if(!stt || !tts) {
                Error(!stt?"recognizer_unavailable":"female_voice_unavailable",true);
                State("off",false); return;
            }
            if(!Acquire()) return;
            // A rapid stop/start may replace a queued stop. Retire the old
            // recognizer/prompt before opening this generation's microphone.
            CancelRecognition(); CancelSpeech(); pendingText=null;
            lock(sync) { wanted=true; paused=false; }
            break;
        case "pause":
            lock(sync) { paused=true; pendingText=null; }
            CancelSpeech(); State("thinking",false); break;
        case "resume": if(!closing) { lock(sync) { paused=false; } } break;
        case "speak":
            string text=Text(d,"text","");
            if(text.Length==0 || text.Length>MaxText) { Error("invalid_speech_text",false); break; }
            foreach(char c in text) if(c<32 && c!='\r' && c!='\n' && c!='\t') {
                Error("invalid_speech_text",false); return;
            }
            if(!wanted || closing) break;
            if(speaking || pendingText!=null) { Error("speech_already_pending",false); break; }
            pendingText=text; lock(sync) { paused=false; } break;
        case "stop":
        case "close":
            lock(sync) { wanted=false; paused=true; pendingText=null; }
            CancelRecognition(); CancelSpeech();
            State("off",recognizer!=null || speaking);
            if(command=="close") closing=true;
            break;
        default: Error("invalid_voice_command",false); break;
        }
    }
    public bool Tick() {
        Action[] ready;
        lock(sync) {
            ready=signals.ToArray(); signals.Clear();
        }
        foreach(Action action in ready) action();
        if(queueOverflow) { queueOverflow=false; Error("speech_event_queue_full",true); }
        if(sapi!=null && speaking) {
            try { if((int)sapi.Status.RunningState==1) {
                speechCompletedSession=promptSession; speaking=false; speechCancel=false;
            } }
            catch { Error("speech_status_failed",true); }
        }
        if(!wanted || paused || pendingText!=null || speaking || closing) CancelRecognition();
        if(!wanted || closing) CancelSpeech();
        if(recognizer==null && !speaking) {
            if(pendingText!=null && wanted && !closing) {
                string text=pendingText; pendingText=null; BeginSpeech(text);
            } else if(wanted && !paused && !closing) {
                BeginRecognition();
            } else {
                if(ownsLease && !wanted) { lease.ReleaseMutex(); ownsLease=false; }
                if(state!="off" && !wanted) State("off",false);
                else if(!wanted) State("off",false);
                if(closing) return false;
            }
        }
        return true;
    }
    public void Dispose() {
        // Called only after Tick observed recognition completion and speech end.
        if(recognizer!=null || speaking) throw new InvalidOperationException("speech disposal pending");
        if(synth!=null) synth.Dispose();
        if(sapi!=null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(sapi);
        if(ownsLease) { lease.ReleaseMutex(); ownsLease=false; }
        lease.Dispose();
    }
    static string ReadBoundedLine() {
        var buffer=new StringBuilder();
        while(true) {
            int c=Console.In.Read();
            if(c<0) return buffer.Length==0 ? null : buffer.ToString();
            if(c=='\n') return buffer.ToString().TrimEnd('\r');
            if(buffer.Length>=MaxLine) throw new ArgumentException("line_limit");
            buffer.Append((char)c);
        }
    }
    static Task<string> NextLine() { return Task.Run((Func<string>)ReadBoundedLine); }
    public static int Run(string mode) {
        var json=new JavaScriptSerializer { MaxJsonLength=MaxLine };
        string first=ReadBoundedLine();
        if(first==null || first.Length>MaxLine) return 2;
        var host=new KiraWindowsSpeech(json.Deserialize<Dictionary<string,object>>(first));
        if(mode=="Capabilities") { host.Capability(); host.Dispose(); return 0; }
        Task<string> line=NextLine();
        bool eof=false;
        while(true) {
            if(!eof && line.IsCompleted) {
                string data=line.GetAwaiter().GetResult();
                if(data==null) {
                    eof=true;
                    host.Command(new Dictionary<string,object>{{"command","close"},{"session",host.session+1}});
                } else {
                    try {
                        if(data.Length>MaxLine) throw new ArgumentException();
                        host.Command(json.Deserialize<Dictionary<string,object>>(data));
                    } catch {
                        host.Error("invalid_voice_input",true);
                        host.Command(new Dictionary<string,object>{{"command","close"},{"session",host.session+1}});
                        eof=true;
                    }
                    if(!eof) line=NextLine();
                }
            }
            if(!host.Tick()) break;
            Thread.Sleep(20);
        }
        host.Dispose(); return 0;
    }
}

public static class KiraSpeechProgram {
    public static int Main(string[] args) {
        Console.InputEncoding = new UTF8Encoding(false, true);
        Console.OutputEncoding = new UTF8Encoding(false);
        if(args.Length != 2 || args[0] != "--mode" ||
           (args[1] != "Host" && args[1] != "Capabilities")) return 2;
        try { return KiraWindowsSpeech.Run(args[1]); }
        catch {
            Console.WriteLine("{\"type\":\"error\",\"session\":0,\"code\":\"windows_speech_framework_unavailable\",\"fatal\":true}");
            return 1;
        }
    }
}

