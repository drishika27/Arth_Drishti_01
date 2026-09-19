const ARTH_BODH_URL = import.meta.env.VITE_ARTH_BODH_URL || "http://localhost:5173";
const ARTH_RAKSHA_URL = import.meta.env.VITE_ARTH_RAKSHA_URL || "http://localhost:5174";

function ArthaMark() {
  // The one deliberate distinguishing motif: अर्थ (artha) — "meaning" and
  // "wealth/purpose" at once. Rendered plainly, not as a logo-mark cliché.
  return (
    <div className="flex items-baseline gap-3">
      <span className="font-serif text-5xl text-thread">अर्थ</span>
      <span className="text-sm text-paper/70 leading-tight max-w-[14rem]">
        meaning and worth, in one word — the root both products share
      </span>
    </div>
  );
}

function SharedEngineDiagram() {
  return (
    <div className="flex items-center justify-center gap-0 my-10">
      <div className="text-center px-4">
        <div className="w-20 h-20 rounded-full border border-thread/50 flex items-center justify-center text-xs text-paper/80">
          bank<br/>statement
        </div>
      </div>
      <div className="h-px w-10 bg-thread/40" />
      <div className="w-24 h-24 rounded-full border-2 border-thread flex items-center justify-center text-center text-xs text-thread px-2">
        finding +<br/>evidence
      </div>
      <div className="h-px w-10 bg-thread/40" />
      <div className="text-center px-4">
        <div className="w-20 h-20 rounded-full border border-thread/50 flex items-center justify-center text-xs text-paper/80">
          wallet<br/>activity
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div className="font-sans">
      {/* 1. Opening moment */}
      <section className="bg-root text-paper px-6 py-24">
        <div className="max-w-2xl mx-auto">
          <ArthaMark />
          <h1 className="font-serif text-4xl md:text-5xl mt-8 leading-tight">
            ArthDrishti reads your money's confusing moments and tells you
            the truth about them — never more, never less.
          </h1>
        </div>
      </section>

      {/* 2. Shared engine idea */}
      <section className="bg-root text-paper px-6 pb-24">
        <div className="max-w-2xl mx-auto">
          <p className="text-paper/80 leading-relaxed">
            A confusing bank fee and a risky wallet approval are, underneath,
            the same shape: a finding, backed by a real number, with a real
            reason. One engine turns that shape into an honest explanation —
            it never invents what it can't prove.
          </p>
          <SharedEngineDiagram />
        </div>
      </section>

      {/* 3. Two products */}
      <section className="grid md:grid-cols-2">
        <a href={ARTH_BODH_URL} className="group block bg-[#F4F6F4] text-[#10181B] px-8 py-20 hover:bg-[#EDF2ED] transition-colors">
          <p className="text-xs uppercase tracking-wide text-[#5B6B66] mb-3">for your bank statement</p>
          <h2 className="font-serif text-3xl text-[#0E6B4E] mb-3">Arth Bodh</h2>
          <p className="text-[#10181B]/80 leading-relaxed max-w-sm">
            Reads a statement or bill and explains every fee, in your own
            language, warmly and plainly — by voice if that's easier.
          </p>
          <span className="inline-block mt-6 text-sm font-medium text-[#0E6B4E] group-hover:underline">
            Open Arth Bodh
          </span>
        </a>
        <a href={ARTH_RAKSHA_URL} className="group block bg-[#EFF4F2] text-[#111B1D] px-8 py-20 hover:bg-[#E6EDEA] transition-colors">
          <p className="text-xs uppercase tracking-wide text-[#5E7370] mb-3">for your crypto wallet</p>
          <h2 className="font-serif text-3xl text-[#0F5E5A] mb-3">Arth Raksha</h2>
          <p className="text-[#111B1D]/80 leading-relaxed max-w-sm">
            Checks your own wallet's risk, explains your own past activity,
            and lets you send crypto in plain language — you always sign.
          </p>
          <span className="inline-block mt-6 text-sm font-medium text-[#0F5E5A] group-hover:underline">
            Open Arth Raksha
          </span>
        </a>
      </section>

      {/* 4. Core principle */}
      <section className="bg-paper px-6 py-24 text-center">
        <p className="font-serif text-3xl md:text-4xl max-w-2xl mx-auto leading-snug text-ink">
          Grounded in evidence. Never invented. Explained honestly.
        </p>
      </section>

      {/* 5. Footer */}
      <footer className="border-t border-ink/10 px-6 py-8 text-center text-sm text-ink/60">
        ArthDrishti — अर्थ दृष्टि — financial vision, grounded in evidence.
      </footer>
    </div>
  );
}
