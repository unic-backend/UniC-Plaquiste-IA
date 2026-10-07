import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, isNative } from "./api";
import * as I from "./Icons";
import { listenOnce } from "./listen";
import { audioRoute, wakeApi } from "./phone";
import { getVocalRate, sayIn, stop as stopSpeech } from "./speech";

/**
 * Interprète : le patron parle français, UniC traduit à voix haute pour son interlocuteur ; l'interlocuteur répond dans sa langue,
 * UniC traduit en français. Seul l'interprète travaille (aucun accès aux données de l'entreprise). Rien n'est enregistré :
 * la mémoire de la conversation vit dans cet écran et s'efface à la fin. Il s'arrête tout seul : bouton Terminer, fermeture,
 * appli quittée, ou 3 minutes sans parole.
 */
export const LANGS: { code: string; name: string; bcp: string }[] = [
  { code: "en", name: "Anglais", bcp: "en-US" }, { code: "ar", name: "Arabe", bcp: "ar-SA" }, { code: "es", name: "Espagnol", bcp: "es-ES" },
  { code: "pt", name: "Portugais", bcp: "pt-PT" }, { code: "de", name: "Allemand", bcp: "de-DE" }, { code: "it", name: "Italien", bcp: "it-IT" },
  { code: "tr", name: "Turc", bcp: "tr-TR" }, { code: "zh", name: "Chinois", bcp: "zh-CN" }, { code: "ru", name: "Russe", bcp: "ru-RU" },
  { code: "nl", name: "Néerlandais", bcp: "nl-NL" }, { code: "ja", name: "Japonais", bcp: "ja-JP" }, { code: "hi", name: "Hindi", bcp: "hi-IN" },
];
const FR = "fr-FR";
const LANG_KEY = "unic.interp.lang";
const IDLE_MS = 3 * 60 * 1000;
const STOP_RE = /^(stop|termin[ée]+|c'est fini|fin de (la )?traduction|arr[êe]te (l'interpr[èe]te|la traduction)|on arr[êe]te)\b/i;

type Side = "me" | "them";
type Turn = { who: Side; src: string; out: string };
type Phase = "idle" | "listening" | "thinking" | "speaking";

const bcpOf = (code: string) => LANGS.find((l) => l.code === code)?.bcp || "en-US";
const nameOf = (code: string) => LANGS.find((l) => l.code === code)?.name || code;

export function Interpreter() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const initial = (() => {
    const q = params.get("lang") || "";
    if (LANGS.some((l) => l.code === q)) return q;
    try { const s = localStorage.getItem(LANG_KEY) || ""; if (LANGS.some((l) => l.code === s)) return s; } catch { /* ignoré */ }
    return "en";
  })();
  const [lang, setLang] = useState(initial);
  const [started, setStarted] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [side, setSide] = useState<Side | null>(null);
  const [ready, setReady] = useState(false);
  const [hearing, setHearing] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [chain, setChain] = useState(true);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const startedRef = useRef(false);
  const langRef = useRef(lang);
  const chainRef = useRef(chain);
  const turnsRef = useRef<Turn[]>([]);
  const gen = useRef(0);
  const ctl = useRef<AbortController | null>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  langRef.current = lang; chainRef.current = chain;

  const touchIdle = () => { clearTimeout(idleTimer.current); idleTimer.current = setTimeout(() => finish("Interprète arrêté : plus de parole depuis 3 minutes."), IDLE_MS); };

  function halt() {   // coupe l'écoute et la parole en cours
    gen.current++;
    ctl.current?.abort(); ctl.current = null;
    stopSpeech();
  }

  function finish(why = "") {
    if (!startedRef.current && !why) return;
    const was = startedRef.current;
    startedRef.current = false;
    clearTimeout(idleTimer.current);
    halt();
    turnsRef.current = []; setTurns([]);   // la mémoire de la conversation s'efface
    setStarted(false); setPhase("idle"); setSide(null); setReady(false); setHearing(false);
    if (was && isNative) { wakeApi.keepScreenOn(false).catch(() => {}); audioRoute(false); wakeApi.resume().catch(() => {}); }
    if (why) setNote(why);
  }

  function start() {
    setErr(""); setNote("");
    try { localStorage.setItem(LANG_KEY, lang); } catch { /* ignoré */ }
    startedRef.current = true; setStarted(true);
    if (isNative) { wakeApi.pause().catch(() => {}); wakeApi.keepScreenOn(true).catch(() => {}); audioRoute(true); }   // « Hey UniC » se tait, l'écran reste allumé
    touchIdle();
  }

  async function converse(first: Side) {
    if (!startedRef.current) return;
    halt();
    const my = ++gen.current;
    const c = new AbortController(); ctl.current = c;
    let who: Side = first, silent = 0;
    const alive = () => startedRef.current && gen.current === my && !c.signal.aborted;
    while (alive()) {
      const code = langRef.current;
      const srcLang = who === "me" ? "fr" : code, dstLang = who === "me" ? code : "fr";
      setSide(who); setPhase("listening"); setReady(false); setHearing(false); touchIdle();
      let heard = "";
      try { heard = await listenOnce(() => setHearing(true), () => setReady(true), who === "me" ? FR : bcpOf(code), c.signal); }
      catch (e: any) { if (alive()) setErr(e?.message || "Micro indisponible"); break; }
      if (!alive()) return;
      setHearing(false);
      if (!heard) { if (++silent >= 2 || !chainRef.current) break; who = who === "me" ? "them" : "me"; continue; }   // silence des deux côtés : on se met en attente
      silent = 0;
      if (who === "me" && STOP_RE.test(heard.trim())) { finish("Interprète terminé."); return; }
      setPhase("thinking");
      let out = "";
      try { out = (await api.unicTranslate(heard, srcLang, dstLang, turnsRef.current.slice(-6).map((t) => ({ who: t.who, text: t.src })))).text; }
      catch (e: any) { if (alive()) setErr(e?.message || "Traduction impossible."); break; }
      if (!alive()) return;
      if (!out || out === "[?]") { setNote("Je n'ai pas bien compris, répète."); continue; }
      setNote("");
      const turn: Turn = { who, src: heard, out };
      turnsRef.current = [...turnsRef.current, turn].slice(-12); setTurns(turnsRef.current);
      setPhase("speaking");
      const r = await sayIn(out, who === "me" ? bcpOf(code) : FR, who === "me" ? 0.95 : getVocalRate());
      if (!alive()) return;
      if (!r.voice && who === "me") setNote(`La voix ${nameOf(code).toLowerCase()} n'est pas installée sur ce téléphone : lis la traduction à l'écran, ou installe-la (Réglages › Synthèse vocale).`);
      if (!chainRef.current) break;
      who = who === "me" ? "them" : "me";   // la parole passe à l'autre
    }
    if (gen.current === my && startedRef.current) { setPhase("idle"); setSide(null); setReady(false); setHearing(false); }
  }

  useEffect(() => {
    const hide = () => { if (document.hidden && startedRef.current) finish("Interprète arrêté : l'appli a été quittée."); };
    document.addEventListener("visibilitychange", hide);
    return () => { document.removeEventListener("visibilitychange", hide); finish(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const last = turns[turns.length - 1];
  const label = phase === "listening" ? (hearing ? "Je t'entends…" : ready ? (side === "me" ? "Parle en français" : `Il parle ${nameOf(lang).toLowerCase()}`) : "Un instant…")
    : phase === "thinking" ? "Je traduis…" : phase === "speaking" ? "Je traduis à voix haute" : started ? "Touche qui parle" : "";

  return createPortal(
    <div className={`interp ${phase === "listening" && !ready ? "thinking" : phase}`} role="application" aria-label="Interprète UniC">
      <button className="unic-close" onClick={() => { finish(); nav(-1); }} aria-label="Fermer"><I.Close size={24} /></button>
      <h1 className="interp-title"><I.Globe size={22} /> Interprète</h1>

      {!started ? (
        <div className="interp-setup">
          <p className="hint">Français ⇄ <b>{nameOf(lang)}</b>. Tu parles, UniC traduit à voix haute ; l'autre répond, UniC te traduit. Seul l'interprète est actif : aucune donnée de l'entreprise, rien d'enregistré.</p>
          <div className="interp-langs" role="group" aria-label="Langue de l'interlocuteur">
            {LANGS.map((l) => <button key={l.code} className={l.code === lang ? "on" : ""} onClick={() => setLang(l.code)}>{l.name}</button>)}
          </div>
          <label className="interp-chain"><input type="checkbox" checked={chain} onChange={(e) => setChain(e.target.checked)} /> Enchaîner : après chaque traduction, j'écoute l'autre personne</label>
          <button className="btn btn-copper interp-start" onClick={start}>Activer l'interprète</button>
          {note && <p className="hint" role="status">{note}</p>}
          {err && <p className="error" role="alert">{err}</p>}
        </div>
      ) : (
        <>
          <div className="interp-out" aria-live="polite">
            {last ? <><p className="interp-src">{last.who === "me" ? "Toi" : "Lui / elle"} : {last.src}</p><p className={`interp-text ${last.who === "me" ? "them" : "me"}`} dir="auto">{last.out}</p></> : <p className="interp-src">La traduction s'affiche ici.</p>}
          </div>
          <p className="unic-state" role="status">{label}</p>
          <div className="interp-btns">
            <button className={`interp-btn ${side === "me" && phase === "listening" ? "live" : ""}`} onClick={() => converse("me")}><I.Mic size={22} /> Moi · Français</button>
            <button className={`interp-btn ${side === "them" && phase === "listening" ? "live" : ""}`} onClick={() => converse("them")}><I.Mic size={22} /> Lui · {nameOf(lang)}</button>
          </div>
          <button className="btn interp-end" onClick={() => finish("Interprète terminé.")}>Terminer</button>
          {note && <p className="hint" role="status">{note}</p>}
          {err && <p className="error" role="alert">{err}</p>}
        </>
      )}
    </div>,
    document.body,
  );
}
