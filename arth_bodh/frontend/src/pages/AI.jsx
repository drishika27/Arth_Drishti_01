import { useRef, useState } from 'react';
import { api } from '../api';
import { Card, Pill } from '../ui';

/** Arth AI chat. Answers come from the server, grounded in THIS user's own data. */
export default function AI({ language }) {
  const [chat, setChat] = useState([{ role: 'assistant', text: 'Namaste. I can help you understand spending, cash flow, or your digital assets. What would you like to explore?' }]);
  const [question, setQuestion] = useState('');
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const recognition = useRef(null);

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

  function startVoice() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { setTranscript('Voice recognition is not available in this browser. You can type instead.'); return; }
    recognition.current = new SR();
    recognition.current.lang = language === 'हिंदी' ? 'hi-IN' : 'en-IN';
    recognition.current.interimResults = true;
    recognition.current.onresult = (e) => setTranscript(Array.from(e.results).map((r) => r[0].transcript).join(''));
    recognition.current.onend = () => setListening(false);
    recognition.current.start();
    setListening(true);
  }
  function stopVoice() { recognition.current?.stop(); setListening(false); }

  return <>
    <div className="section-intro"><Pill tone="purple">Arth AI</Pill><h2>A calmer way to ask about money.</h2><p>Ask about your spending patterns, explain a transaction, or turn a voice note into an expense.</p></div>
    <Card className="chat-card">
      <div className="suggestions">{['Why did I spend more this month?', 'What is my largest category?', 'Summarize my cash flow', 'Any unusual transactions?'].map((x) => <button key={x} onClick={() => ask(x)}>{x}</button>)}</div>
      <div className="chat-window">{chat.map((m, i) => <div key={i} className={`bubble ${m.role}`}>{m.text}</div>)}</div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask Arth AI…" />
        <button type="button" className={listening ? 'voice active' : 'voice'} onClick={listening ? stopVoice : startVoice}>{listening ? '■' : '●'}</button>
        <button className="primary">Send</button>
      </form>
      <div className="voice-review"><label>Voice transcription</label><textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} placeholder="Your transcription appears here for review…" /><button className="secondary" onClick={() => ask(transcript)}>Send transcription</button></div>
    </Card>
  </>;
}
