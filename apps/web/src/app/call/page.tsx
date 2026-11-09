"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Badge, Card } from "@/components/ui";
import { API, money, post, usePoll } from "@/lib/api";

type Line = { role: "agent" | "caller"; text: string; agent?: string; llm?: string | null; voice?: string };
type CallState = { id: string; stage: string | null; pay_link: string | null; total: string | null; tip?: string; status: string; order_id: string | null };
type TurnOut = { say: string; agent: string; llm: string | null; end_call: boolean; call: CallState };
type Menu = { id: string; name: string; currency: string; menu: { id: string; name: string; price: string }[] }[];
const LANGUAGES = { en: "en-US", hi: "hi-IN", ta: "ta-IN", es: "es-ES" } as const;

/* eslint-disable @typescript-eslint/no-explicit-any */
const SpeechRec: any = typeof window !== "undefined" ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : null;

export default function CallWidget() {
  const menu = usePoll<Menu>("/businesses", 60000);
  const [call, setCall] = useState<CallState | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState<keyof typeof LANGUAGES>("en");
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [voice, setVoice] = useState(true);
  const [sttMode, setSttMode] = useState<string>("browser");
  const recRef = useRef<any>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const callRef = useRef<CallState | null>(null);
  const busyRef = useRef(false); // one caller turn at a time, like a real phone line
  const logRef = useRef<HTMLDivElement>(null);
  callRef.current = call;

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [lines]);

  /** TTS chain: server (ElevenLabs -> Cartesia -> OpenAI) then the browser's own voice. */
  const speak = useCallback(async (say: string): Promise<string> => {
    if (!voice) return "muted";
    try {
      const r = await fetch(`${API}/voice/tts`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: say }) });
      if (r.ok) {
        const audio = new Audio(URL.createObjectURL(await r.blob()));
        await new Promise<void>((res) => { audio.onended = () => res(); audio.onerror = () => res(); audio.play().catch(() => res()); });
        return r.headers.get("X-Provider") ?? "server";
      }
    } catch {}
    if ("speechSynthesis" in window) {
      await new Promise<void>((res) => {
        const u = new SpeechSynthesisUtterance(say);
        u.lang = LANGUAGES[language];
        u.rate = 1.05;
        u.onend = () => res();
        u.onerror = () => res();
        speechSynthesis.cancel();
        speechSynthesis.speak(u);
      });
      return "browser";
    }
    return "text";
  }, [voice, language]);

  const agentSays = useCallback(async (say: string, agent?: string, llm?: string | null) => {
    const idx = Date.now();
    setLines((l) => [...l, { role: "agent", text: say, agent, llm }]);
    const used = await speak(say);
    setLines((l) => l.map((x, i) => (i === l.length - 1 && x.text === say ? { ...x, voice: used } : x)));
    return idx;
  }, [speak]);

  // Coming back from PayPal (?resume=<call id>): reload the call and let the payment check confirm it.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("resume");
    if (!id) return;
    fetch(`${API}/calls/${id}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((c: (CallState & { transcript: Line[] }) | null) => {
        if (!c) return;
        setCall(c);
        setLines(c.transcript.map((t) => ({ role: t.role, text: t.text, agent: t.agent, llm: t.llm })));
        window.history.replaceState(null, "", "/call");
      })
      .catch(() => {});
  }, []);

  async function start() {
    setLines([]);
    setBusy(true);
    try {
      const c = await post<CallState & { say: string }>("/calls", { caller: phone || null, language });
      setCall(c);
      await agentSays(c.say, "planner");
    } finally {
      setBusy(false);
    }
  }

  async function send(said: string) {
    const c = callRef.current;
    if (!c || !said.trim() || c.status !== "active" || busyRef.current) return;
    busyRef.current = true;
    setLines((l) => [...l, { role: "caller", text: said }]);
    setText("");
    setBusy(true);
    try {
      const t = await post<TurnOut>(`/calls/${c.id}/turn`, { text: said });
      setCall(t.call);
      await agentSays(t.say, t.agent, t.llm);
      if (t.end_call) await hangup();
    } catch (e) {
      setLines((l) => [...l, { role: "agent", text: `(connection problem: ${(e as Error).message})`, agent: "system" }]);
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }

  async function hangup() {
    const c = callRef.current;
    recRef.current?.stop?.();
    if (c && c.status === "active") setCall(await post<CallState>(`/calls/${c.id}/end`));
  }

  // While waiting for PayPal, check every 2s so the agent confirms the moment the payment lands.
  useEffect(() => {
    if (call?.stage !== "awaiting_payment" || call.status !== "active") return;
    const t = setInterval(async () => {
      const r = await post<{ say: string | null }>(`/calls/${call.id}/poll`).catch(() => ({ say: null }));
      if (r.say) {
        setCall((c) => (c ? { ...c, stage: "done" } : c));
        await agentSays(r.say, "payments");
      }
    }, 2000);
    return () => clearInterval(t);
  }, [call?.stage, call?.status, call?.id, agentSays]);

  /** STT: browser Web Speech API when available; otherwise record and use the server chain (Deepgram -> AssemblyAI -> Whisper). */
  async function listen() {
    if (listening) {
      recRef.current?.stop?.();
      mediaRef.current?.stop();
      return;
    }
    if (SpeechRec && sttMode === "browser") {
      const rec = new SpeechRec();
      rec.lang = LANGUAGES[language];
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.onresult = (e: any) => send(e.results[0][0].transcript);
      rec.onend = () => setListening(false);
      rec.onerror = () => setListening(false);
      recRef.current = rec;
      setListening(true);
      rec.start();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setListening(false);
        const fd = new FormData();
        fd.append("audio", new Blob(chunks, { type: mr.mimeType }), "speech.webm");
        const r = await fetch(`${API}/voice/stt`, { method: "POST", body: fd });
        if (r.ok) {
          const d = await r.json();
          setSttMode(`server:${d.provider}`);
          send(d.text);
        } else {
          setLines((l) => [...l, { role: "agent", text: "(No speech-to-text provider available. Please type instead.)", agent: "system" }]);
        }
      };
      mediaRef.current = mr;
      setListening(true);
      mr.start();
      setTimeout(() => mr.state === "recording" && mr.stop(), 6000);
    } catch {
      setLines((l) => [...l, { role: "agent", text: "(Microphone unavailable. Please type instead.)", agent: "system" }]);
    }
  }

  const active = call?.status === "active";
  const biz = menu.data?.[0];

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-2" title={biz ? `Call ${biz.name}` : "Call"} right={
        <div className="flex items-center gap-2 text-xs">
          {call && <Badge tone={active ? "green" : "gray"}>{active ? "on call" : call.status}</Badge>}
          {call?.stage && <Badge tone="blue">{call.stage}</Badge>}
          <label className="flex items-center gap-1 text-muted"><input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} /> voice</label>
        </div>
      }>
        <div ref={logRef} className="h-[420px] overflow-auto space-y-2 rounded-lg bg-fg/[0.03] p-3">
          {!lines.length && (
            <div className="h-full grid place-items-center text-center text-sm text-muted">
              <div>
                <div className="text-4xl mb-2">☎</div>
                Press <b>Call</b>, then talk (or type) like you&apos;re ordering at a food truck.<br />
                Try: “two carne asada tacos and a horchata”, then “that&apos;s it”, then “yes”.
              </div>
            </div>
          )}
          {lines.map((l, i) => (
            <div key={i} className={`flex ${l.role === "agent" ? "" : "justify-end"}`}>
              <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${l.role === "agent" ? "bg-panel border border-line" : "bg-brand text-white"}`}>
                {l.text}
                {l.role === "agent" && l.agent && l.agent !== "system" && (
                  <div className="text-[10px] mt-1 text-muted">
                    {l.agent} · {l.llm ?? (l.agent === "planner" ? "greeting" : "rules")}{l.voice ? ` · voice: ${l.voice}` : ""}
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && <div className="text-xs text-muted animate-pulse">agent is thinking…</div>}
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-3">
          {!active ? (
            <>
              <input className="w-44 rounded-md border border-line bg-transparent px-3 py-2 text-sm" placeholder="Your phone (optional, for SMS)" value={phone} onChange={(e) => setPhone(e.target.value)} />
              <label className="text-xs text-muted">Language <select className="ml-1 rounded-md border border-line bg-panel px-2 py-2 text-fg" value={language} onChange={(e) => setLanguage(e.target.value as keyof typeof LANGUAGES)}><option value="en">English</option><option value="hi">हिन्दी</option><option value="ta">தமிழ்</option><option value="es">Español</option></select></label>
              <button onClick={start} disabled={busy} className="rounded-full bg-ok text-white px-6 py-2 font-medium disabled:opacity-50">Call</button>
            </>
          ) : (
            <>
              <button onClick={listen} disabled={busy && !listening}
                className={`w-12 h-12 rounded-full grid place-items-center text-xl ${listening ? "bg-bad text-white listening" : "bg-brand text-white"}`} title="Hold a conversation">
                {listening ? "■" : "🎙"}
              </button>
              <form className="flex-1 flex gap-2 min-w-[200px]" onSubmit={(e) => { e.preventDefault(); send(text); }}>
                <input className="flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm" placeholder={busy ? "Agent is replying…" : "…or type what you'd say"} disabled={busy} value={text} onChange={(e) => setText(e.target.value)} />
              </form>
              <button onClick={hangup} className="rounded-full bg-bad text-white px-5 py-2 font-medium">Hang up</button>
            </>
          )}
        </div>
        <div className="text-[11px] text-muted mt-2">
          Speech-to-text: {SpeechRec ? sttMode : "server chain (Deepgram → AssemblyAI → Whisper)"} · Text-to-speech: ElevenLabs → Cartesia → OpenAI → browser voice
        </div>
      </Card>
      <div className="space-y-4">
        {call?.pay_link && (
          <Card title="Your PayPal link" right={<Badge tone={call.stage === "done" ? "green" : "amber"}>{call.stage === "done" ? "paid" : "waiting"}</Badge>}>
            <div className="text-2xl font-semibold mb-2">{money(call.total)}</div>
            {call.stage === "done" ? (
              <div className="text-sm text-ok">Payment received. The agent confirmed it on the call.</div>
            ) : (
              <>
                {Number(call.tip ?? 0) > 0 && <p className="mb-2 text-xs text-muted">Includes a {money(call.tip)} crew tip.</p>}
                <div className="mb-3 flex flex-col items-center gap-1 rounded-lg border border-line bg-white p-3">
                  <QRCodeSVG value={call.pay_link} size={160} level="M" title="Scan to open PayPal checkout" />
                  <span className="text-xs text-gray-600">Scan to pay on your phone</span>
                </div>
                <a href={call.pay_link} target="_blank" rel="noreferrer" className="block text-center rounded-full bg-[#ffc439] text-[#111] font-semibold py-2.5">Pay with PayPal</a>
                <p className="text-xs text-muted mt-2">Sandbox: log in with a sandbox personal account. Stay on the call; the agent confirms when PayPal does.</p>
              </>
            )}
          </Card>
        )}
        <Card title="Menu">
          <ul className="text-sm space-y-1">
            {biz?.menu.map((m) => <li key={m.id} className="flex justify-between"><span>{m.name}</span><span className="tabular-nums">{money(m.price)}</span></li>)}
          </ul>
          <p className="text-xs text-muted mt-3">Prices come only from this menu. The AI can&apos;t change them.</p>
        </Card>
      </div>
    </div>
  );
}
