import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api, isNative, Stopped } from "./api";
import * as I from "./Icons";
import { listenOnce } from "./listen";
import { audioOutputs, audioRoute, getPhoneWhenLocked, getReadWhenLocked, getVoiceOutput, isWakeScreen, notifApi, phone, setVoiceOutput, wakeApi, type VoiceOutput } from "./phone";
import { looksLikePhoneTask, runNotifCommand, type Notif } from "./notifs";
import { createSpeaker, ding, getSpeechIssue, getVocalRate, getVoiceOption, keepVoiceConv, lastVoiceConv, say as sayRate, stop as stopSpeech } from "./speech";
import { parseTimer, runTimer } from "./timers";
import { END_RE, HANGUP_RE, isContinuation, runPhoneIntent, wholeSentence, type Intent } from "./unicPhone";
import type { SpeechPipeline } from "./sentences";

/** UniC vocal : on lui parle, il répond à voix haute. Rien n'est écrit à l'écran. Dire « stop » ou « merci » termine. */
type Phase = "idle" | "listening" | "thinking" | "speaking";
const LABEL: Record<Phase, string> = { idle: "Touche pour parler", listening: "Je t'écoute", thinking: "Je réfléchis…", speaking: "Je parle · touche pour me couper" };
const HEARING = "Je t'entends…";
const WAITING = "Un instant…";   // le micro n'est pas encore ouvert : on n'affiche « Je t'écoute » qu'au signal sonore
/** « mode interprète », « active la traduction en anglais » → ouvre l'interprète (la langue citée est préchoisie). */
const INTERP_RE = /interpr[èe]te|traducteur|mode traduction|(?:active|lance|ouvre|d[ée]marre)\s+(?:la\s+)?traduction/i;
const INTERP_LANGS: [RegExp, string][] = [[/anglais|english/i, "en"], [/arabe/i, "ar"], [/espagnol/i, "es"], [/portugais/i, "pt"], [/allemand/i, "de"], [/italien/i, "it"], [/turc/i, "tr"], [/chinois/i, "zh"], [/russe/i, "ru"], [/n[ée]erlandais|hollandais/i, "nl"], [/japonais/i, "ja"], [/hindi/i, "hi"]];

const say = (t: string) => sayRate(t, getVocalRate());   // UniC vocal parle à la vitesse choisie (1,25 par défaut)
/** Minuteur terminé dans le navigateur (le téléphone, lui, sonne par une notification) : trois tons puis la voix. */
const ring = (label: string) => { ding(880); setTimeout(() => ding(988), 260); setTimeout(() => ding(1175), 520); setTimeout(() => { say(`Minuteur terminé${label ? ` : ${label}` : ""}.`); }, 900); };

export function UnicVoice() {
  const nav = useNavigate();
  const [phase, setPhase] = useState<Phase>("idle");
  const [err, setErr] = useState("");
  const [hearing, setHearing] = useState(false);
  const [ready, setReady] = useState(false);   // micro réellement ouvert
  const [out, setOut] = useState<VoiceOutput>(getVoiceOutput());   // où UniC parle : haut-parleur ou Bluetooth
  const [bt, setBt] = useState("");   // nom de l'appareil Bluetooth connecté ("" = aucun)
  const [said, setSaid] = useState("");   // dernière phrase comprise : on voit tout de suite si le micro entend
  const active = useRef(false);
  const cid = useRef<string | undefined>(lastVoiceConv());   // rouvert dans les 30 min : la même conversation continue
  const queue = useRef<{ items: Notif[]; index: number }>({ items: [], index: 0 });
  const failed = useRef(false);   // erreur affichée : l'écran reste ouvert pour qu'on la lise
  const manual = useRef(false);   // arrêt par un toucher : on ne ferme pas
  const interp = useRef("");   // l'interprète a été demandé à voix haute : on y va quand la conversation se termine
  const wake = useRef(isWakeScreen());   // ouvert par « Hey UniC »
  const speaking = useRef<SpeechPipeline | null>(null);
  const quietEar = useRef<AbortController | null>(null);   // écoute discrète pendant la réflexion : toujours refermée (fin, erreur, fermeture)   // réponse en cours de lecture : la toucher la coupe et UniC réécoute

  const refreshBt = () => { if (isNative) audioOutputs().then((o) => setBt(o.bluetooth || "")); };
  async function switchOut() {
    const next: VoiceOutput = out === "speaker" ? "bluetooth" : "speaker";
    if (next === "bluetooth" && !bt) { setErr("Aucun appareil Bluetooth connecté. Connecte-le dans les réglages du téléphone."); return; }
    setErr("");
    setVoiceOutput(next);
    setOut(next);
    audioRoute(next === "bluetooth");   // micro du casque seulement en mode Bluetooth
    await say(next === "bluetooth" ? "Je parle dans le Bluetooth." : "Je parle dans le haut-parleur.");   // on entend tout de suite où part le son
  }

  const end = () => { active.current = false; quietEar.current?.abort(); stopSpeech(); setPhase("idle"); };

  async function conversation() {
    let silent = 0;
    let carry = "";   // phrase entière à renvoyer (le patron a continué de parler pendant que UniC réfléchissait)
    while (active.current) {
      const issue = getSpeechIssue();
      if (issue) setErr(issue);   // la voix de réponse est muette : on le dit à l'écran (sinon « il ne répond pas » sans raison visible)
      setPhase("listening");
      setHearing(false);
      setReady(false);
      let heard = carry;
      carry = "";
      if (!heard) {
        try { heard = await listenOnce(() => setHearing(true), () => setReady(true)); } catch (e: any) { failed.current = true; setErr(e?.message || "Micro indisponible"); return; }
      }
      setHearing(false);
      if (!active.current) return;
      if (!heard) { if (++silent >= 3) { setErr("Je ne t'entends pas. Touche la bille quand tu veux me parler."); await say("Je ne t'entends pas. Touche la bille quand tu veux me parler."); return; } continue; }   // silence : on réécoute tout de suite, sans quitter
      silent = 0;
      setSaid(heard.replace(/^Je reprends ma phrase en entier[^:]*:\s*/, "").trim());
      ding();   // « j'ai entendu » : retour immédiat pendant que UniC réfléchit
      if (END_RE.test(heard.trim())) { await say("D'accord. À tout de suite."); return; }
      if (INTERP_RE.test(heard)) {   // l'interprète a son propre écran : il s'active seulement ici, sur demande
        if (wake.current) { setPhase("speaking"); await say("Ouvre l'application pour l'interprète."); continue; }
        const l = INTERP_LANGS.find(([re]) => re.test(heard))?.[1];
        setPhase("speaking"); await say("J'ouvre l'interprète. Touche qui parle.");
        interp.current = l ? `/interprete?lang=${l}` : "/interprete";
        return;
      }
      const timer = getVoiceOption("timers") ? parseTimer(heard) : null;   // « minuteur 20 minutes » : tout se fait sur le téléphone
      if (timer) {
        setPhase("speaking");
        try { await say(await runTimer(timer, ring)); } catch (e: any) { await say(e?.message || "Je n'ai pas pu lancer le minuteur."); }
        continue;
      }
      if (isNative && HANGUP_RE.test(heard)) {   // « coupe l'appel » : raccrocher tout de suite
        setPhase("speaking");
        try { await say((await phone.endCall()) ? "C'est fait, appel terminé." : "Il n'y a pas d'appel en cours."); }
        catch (e: any) { await say(e?.message || "Je n'ai pas pu raccrocher."); }
        continue;
      }
      setPhase("thinking");
      const locked = isNative ? await notifApi.locked().catch(() => true) : false;   // en cas de doute : verrouillé
      let reply = "";
      try {
        if (isNative) {   // notifications : « qu'est-ce que j'ai reçu », « lis-moi le message » (tout reste sur le téléphone)
          let handled = false;
          setPhase("speaking");
          try { handled = await runNotifCommand(heard, { say, api: notifApi, readWhenLocked: getReadWhenLocked(), queue: queue.current }); }
          catch (e: any) { await say(e?.message || "Je n'ai pas pu lire tes notifications."); handled = true; }
          if (handled) continue;
          setPhase("thinking");
        }
        const it = looksLikePhoneTask(heard) ? await api.unicIntent(heard).catch(() => null) : null;   // pas d'aller-retour serveur si la phrase ne parle ni d'appel ni de message
        if (it && (it.action === "call" || it.action === "sms")) {   // tâche du téléphone : toujours confirmée à voix haute avant d'agir
          if (locked && !getPhoneWhenLocked()) { setPhase("speaking"); await say("Déverrouille le téléphone pour ça."); continue; }
          if (!isNative) { await say("Appeler et envoyer des messages marche seulement dans l'application Android."); continue; }
          setPhase("speaking");
          try {
            await runPhoneIntent(it as Intent, { say, listen: async () => { setPhase("listening"); setReady(false); const h = await listenOnce(undefined, () => setReady(true)); setPhase("speaking"); return h; }, phone,
              polish: async (t) => (await api.unicPolish(t).catch(() => ({ message: t }))).message });
          } catch (e: any) { await say(e?.message || "Je n'ai pas pu le faire."); }
          continue;
        }
        let speaker = createSpeaker();
        speaking.current = speaker;
        let started = false;
        const ac = new AbortController();
        // Suite de phrase : pendant qu'il réfléchit, le micro reste ouvert, sans bip. Le patron continue de parler : la réponse n'est pas
        // lue, on attend la fin de sa phrase et la phrase entière repart. Dès que UniC commence à parler, cette écoute s'arrête.
        const more = { text: "", talking: false };
        const quiet = new AbortController();
        quietEar.current = quiet;
        const extra = getVoiceOption("continue")
          ? listenOnce((t) => { more.text = t; if (isContinuation(t)) { more.talking = true; setHearing(true); } }, undefined, "fr-FR", quiet.signal, true)
            .then((t) => { if (t) more.text = t; }).catch(() => {})
          : Promise.resolve();
        const stuck = window.setTimeout(() => ac.abort(), 70000);   // le serveur ne répond pas : on le dit au lieu de rester sur « Je réfléchis… » pour toujours
        let out;
        try {
          out = await api.chatStream({ message: heard, conversation_id: cid.current, voice: true, locked }, (ev) => {
            if (!active.current) { speaker.cancel(); return; }
            if (more.talking) return;   // le patron parle encore : cette réponse ne sera pas lue
            if (ev.t === "delta") { if (!started) { quiet.abort(); started = true; setPhase("speaking"); } speaker.push(ev.text || ""); }   // il parle dès la première phrase
            else if (ev.t === "reset") { speaker.cancel(); speaker = createSpeaker(); speaking.current = speaker; started = false; }
          }, ac.signal);
        } finally { window.clearTimeout(stuck); }
        cid.current = out.conversation_id;
        keepVoiceConv(cid.current);
        if (more.talking) {   // il parlait encore : on attend la fin de sa phrase et on renvoie la phrase entière
          speaker.cancel();
          speaking.current = null;
          setPhase("listening");
          await extra;
          setHearing(false);
          if (!active.current) return;
          if (END_RE.test(more.text.trim())) { setPhase("speaking"); await say("D'accord. À tout de suite."); return; }
          carry = wholeSentence(heard, more.text);
          continue;
        }
        quiet.abort();
        if (!out.streamed) speaker.push(out.message?.content || "");
        setPhase("speaking");
        try { await speaker.finish(); } finally { speaking.current = null; }
        continue;
      } catch (e: any) {
        quietEar.current?.abort();
        if (cid.current && /introuvable/i.test(e?.message || "")) { cid.current = undefined; carry = heard; continue; }   // conversation reprise mais supprimée entre-temps : on repart d'une neuve
        reply = e instanceof Stopped ? "Le serveur met trop de temps à répondre. Réessaie dans un instant." : (e?.message || "Je n'arrive pas à joindre le serveur."); setErr(reply); }
      if (!active.current) return;
      setPhase("speaking");
      await say(reply);
    }
  }

  const loop = async () => {
    try { await conversation(); } finally { end(); if (interp.current) { const to = interp.current; interp.current = ""; nav(to); return; } if (wake.current && !failed.current && !manual.current) wakeApi.finish().catch(() => {}); }   // « Hey UniC » : on referme et on remet l'écoute
  };

  const begin = () => { setErr(""); failed.current = false; manual.current = false; active.current = true; loop().catch((e) => setErr(e?.message || "Erreur")); };
  const toggle = () => {
    if (active.current && phase === "speaking" && speaking.current) { speaking.current.cancel(); speaking.current = null; return; }   // couper la parole : UniC se tait et réécoute
    if (active.current) { manual.current = true; end(); } else begin();
  };
  const close = () => { end(); if (wake.current) wakeApi.finish().catch(() => {}); else nav(-1); };

  useEffect(() => {
    // téléphone verrouillé : cet écran (seulement lui) peut s'afficher par-dessus l'écran de verrouillage
    if (isNative) { notifApi.lockScreenMode(true).catch(() => {}); audioRoute(getVoiceOutput() === "bluetooth"); refreshBt(); }   // micro du casque seulement si la sortie choisie est le Bluetooth
    const auto = wake.current ? window.setTimeout(() => { if (!active.current) begin(); }, 350) : 0;   // « Hey UniC » : il écoute tout de suite
    // appli quittée (hors « Hey UniC » par-dessus l'écran verrouillé) : plus d'écoute ni de voix en arrière-plan
    const away = () => { if (document.hidden && !wake.current && active.current) { manual.current = true; end(); } };
    document.addEventListener("visibilitychange", away);
    return () => { document.removeEventListener("visibilitychange", away); window.clearTimeout(auto); active.current = false; stopSpeech(); if (isNative) { notifApi.lockScreenMode(false).catch(() => {}); audioRoute(false); } };
  }, []);

  return createPortal(
    <div className={`unic-voice ${phase === "listening" && !ready ? "thinking" : phase}${hearing ? " hearing" : ""}`} role="application" aria-label="UniC vocal">
      <button className="unic-close" onClick={close} aria-label="Fermer"><I.Close size={24} /></button>
      <button className="unic-orb" onClick={toggle} aria-label={LABEL[phase]}>
        <span className="unic-ring r1" /><span className="unic-ring r2" /><span className="unic-core"><I.Mic size={44} /></span>
      </button>
      <p className="unic-state" role="status" aria-live="polite">{phase === "listening" ? (hearing ? HEARING : ready ? LABEL.listening : WAITING) : LABEL[phase]}</p>
      {isNative && (
        <button className="unic-out" onClick={switchOut} aria-label="Changer la sortie du son : haut-parleur ou Bluetooth">
          <I.Speaker size={16} /> {out === "bluetooth" ? `Bluetooth${bt ? " · " + bt : ""}` : "Haut-parleur"}{bt || out === "bluetooth" ? " ⇄" : ""}
        </button>
      )}
      {said && phase !== "idle" && <p className="unic-said">« {said} »</p>}
      {err && <p className="error" role="alert">{err}</p>}
    </div>,
    document.body,
  );
}
