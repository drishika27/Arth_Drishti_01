import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Card, Pill } from '../ui';

const SpeechRecognition = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

// Human-readable reasons for the browser's speech-recognition error codes.
const VOICE_ERRORS = {
  'not-allowed': 'Microphone access is blocked. Click the lock icon in the address bar, allow the microphone, and try again.',
  'service-not-allowed': 'Microphone access is blocked. Allow the microphone for this site and try again.',
  'no-speech': "I didn't hear anything. Tap the mic and speak a little closer.",
  'audio-capture': 'No microphone was found. Plug one in or check your system sound settings.',
  network: "Voice recognition needs an internet connection (the browser sends audio to its speech service). Check your connection and retry.",
  aborted: '',
};

/** Arth AI chat. Answers come from the server, grounded in THIS user's own data. */
export default function AI({ language }) {
  const [chat, setChat] = useState([{ role: 'assistant', text: 'Namaste. I can help you understand spending, cash flow, or your digital assets. What would you like to explore?' }]);
  const [question, setQuestion] = useState('');
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [voiceError, setVoiceError] = useState('');
  const recognition = useRef(null);
  const heard = useRef('');           // final transcript for the current session (state is stale inside callbacks)
  const failed = useRef(false);

  useEffect(() => () => recognition.current?.abort?.(), []);   // stop the mic if the page is left

  async function ask(text = question) {
    const q = (text || '').trim();
    if (!q) return;
    setQuestion('');
    setChat((c) => [...c, { role: 'user', text: q }, { role: 'assistant', text: 'Thinking…', pending: true }]);
    try {
      const d = await api.post('/ai/chat', { question: q });
      setChat((c) => [...c.slice(0, -1), { role: 'assistant', text: d.answer }]);
    } catch (e) {
      setChat((c) => [...c.slice(0, -1), { role: 'assistant', text: `I couldn't answer that: ${e.message}` }]);
    }
  }

  async function startVoice() {
    setVoiceError('');
    if (!SpeechRecognition) {
      setVoiceError('Voice input works in Chrome, Edge or Safari. This browser does not support it — you can type instead.');
      return;
    }
    if (!window.isSecureContext) {
      setVoiceError('Voice input needs a secure page (https:// or localhost).');
      return;
    }
    // Ask for the mic explicitly first so the permission prompt appears and a denial gives a clear message.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
    } catch (e) {
      setVoiceError(e?.name === 'NotFoundError' ? VOICE_ERRORS['audio-capture'] : VOICE_ERRORS['not-allowed']);
      return;
    }

    const rec = new SpeechRecognition();
    rec.lang = language === 'हिंदी' ? 'hi-IN' : 'en-IN';
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    heard.current = '';
    failed.current = false;
    setTranscript('');

    rec.onresult = (e) => {
      let final = '', interim = '';
      for (const r of Array.from(e.results)) {
        if (r.isFinal) final += r[0].transcript;
        else interim += r[0].transcript;
      }
      heard.current = final.trim();
      setTranscript((final + interim).trim());
    };
    rec.onerror = (e) => {
      failed.current = true;
      const msg = VOICE_ERRORS[e.error];
      setVoiceError(msg === undefined ? `Voice input stopped (${e.error}). Please try again.` : msg);
    };
    rec.onend = () => {
      setListening(false);
      recognition.current = null;
      // Speech finished normally: send what was heard straight away.
      if (!failed.current && heard.current) ask(heard.current);
      else if (!failed.current && !heard.current) setVoiceError(VOICE_ERRORS['no-speech']);
    };

    try {
      rec.start();
      recognition.current = rec;
      setListening(true);
    } catch {
      setVoiceError('Could not start the microphone. Wait a moment and try again.');
    }
  }
  function stopVoice() { recognition.current?.stop(); }   // onend then sends what was heard

  return <>
    <div className="section-intro"><Pill tone="purple">Arth AI</Pill><h2>A calmer way to ask about money.</h2><p>Ask about your spending patterns, explain a transaction, or tap the mic and just say it.</p></div>
    <Card className="chat-card">
      <div className="suggestions">{['Why did I spend more this month?', 'What is my largest category?', 'Summarize my cash flow', 'Any unusual transactions?'].map((x) => <button key={x} onClick={() => ask(x)}>{x}</button>)}</div>
      <div className="chat-window">{chat.map((m, i) => <div key={i} className={`bubble ${m.role}`}>{m.text}</div>)}</div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={listening ? 'Listening…' : 'Ask Arth AI…'} />
        <button type="button" className={listening ? 'voice active' : 'voice'} onClick={listening ? stopVoice : startVoice} title={listening ? 'Stop and send' : 'Speak your question'} aria-label={listening ? 'Stop listening' : 'Start voice input'}>{listening ? '■' : '●'}</button>
        <button className="primary">Send</button>
      </form>
      {listening && <div className="notice">Listening… speak now, then tap ■ (or just pause) to send.</div>}
      {voiceError && <div className="notice error">{voiceError}</div>}
      <div className="voice-review"><label>Voice transcription</label><textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} placeholder="What you say appears here…" /><button className="secondary" disabled={!transcript.trim()} onClick={() => ask(transcript)}>Send transcription again</button></div>
    </Card>
  </>;
}
