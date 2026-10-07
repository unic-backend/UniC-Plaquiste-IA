import { apiUrl, getCode, isNative } from "./api";
import { useEffect, useState } from "react";
import { SpeechPipeline } from "./sentences";

/** Lecture à voix haute des réponses. Moteurs : voix du téléphone (gratuit) ou voix ElevenLabs (serveur, voix clonée possible). */
export type VoicePref = { engine: "device" | "eleven"; deviceVoice: string; rate: number };
const KEY = "unic.voice";

export function getPref(): VoicePref {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "{}"); return { engine: v.engine === "eleven" ? "eleven" : "device", deviceVoice: v.deviceVoice || "", rate: Number(v.rate) || 1 }; }
  catch { return { engine: "device", deviceVoice: "", rate: 1 }; }
}
export function setPref(p: Partial<VoicePref>): VoicePref {
  const n = { ...getPref(), ...p };
  try { localStorage.setItem(KEY, JSON.stringify(n)); } catch { /* ignoré */ }
  return n;
}

/** Texte lisible : sans Markdown, tableaux, liens ni sources (le serveur nettoie aussi, par sécurité). */
export function speakable(text: string): string {
  return text.split("\n\n**Sources**")[0]
    .replace(/```[\s\S]*?```/g, " ").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/https?:\/\/\S+/g, " ")
    .replace(/^\s*\|.*\|\s*$/gm, " ").replace(/^\s{0,3}#{1,6}\s*/gm, "").replace(/^\s*[-*•]\s+/gm, "")
    .replace(/[*_`>~]+/g, "").replace(/m²|m2/g, " mètres carrés").replace(/FCFA/g, " francs CFA")
    .replace(/\s*\n+\s*/g, ". ").replace(/\s{2,}/g, " ").replace(/\.{2,}/g, ".").trim();
}

type Listener = () => void;
let playing: string | null = null;
let loading: string | null = null;
let audio: HTMLAudioElement | null = null;
const cache = new Map<string, string>();
const listeners = new Set<Listener>();
const emit = () => listeners.forEach((l) => l());

export function stop(): void {
  try { window.speechSynthesis?.cancel(); } catch { /* ignoré */ }
  if (audio) { audio.pause(); audio = null; }
  playing = null; loading = null; emit();
}

export function deviceVoices(): SpeechSynthesisVoice[] {
  try { return (window.speechSynthesis?.getVoices() || []).filter((v) => v.lang.toLowerCase().startsWith("fr")); } catch { return []; }
}

export function speakDevice(text: string, voiceURI = "", rate = 1, onEnd?: () => void): boolean {
  const synth = window.speechSynthesis;
  if (!synth || typeof SpeechSynthesisUtterance === "undefined") return false;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "fr-FR"; u.rate = rate;
  const v = deviceVoices().find((x) => x.voiceURI === voiceURI);
  if (v) u.voice = v;
  u.onend = () => onEnd?.();
  u.onerror = () => onEnd?.();
  synth.speak(u);
  return true;
}

async function elevenBlob(text: string, voiceId = ""): Promise<string> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const code = getCode();
  if (code) headers.set("X-Access-Code", code);
  const res = await fetch(apiUrl("/api/voice/speak"), { method: "POST", headers, body: JSON.stringify({ text, voice_id: voiceId }) });
  if (!res.ok) {
    let d = res.statusText;
    try { d = (await res.json()).detail || d; } catch { /* ignoré */ }
    throw new Error(typeof d === "string" ? d : "Lecture impossible");
  }
  return URL.createObjectURL(await res.blob());
}

/** Lit (ou arrête) le message `id`. Rend un message d'erreur lisible, ou "" si tout va bien. */
export async function toggle(id: string, text: string): Promise<string> {
  if (playing === id || loading === id) { stop(); return ""; }
  stop();
  const pref = getPref();
  const spoken = speakable(text);
  if (!spoken) return "Rien à lire dans ce message.";
  if (pref.engine === "device") {
    playing = id; emit();
    const ok = speakDevice(spoken, pref.deviceVoice, pref.rate, () => { if (playing === id) { playing = null; emit(); } });
    if (!ok) { playing = null; emit(); return "Ce téléphone n'a pas de voix de lecture. Installe « Synthèse vocale Google » dans les réglages Android."; }
    return "";
  }
  loading = id; emit();
  try {
    let url = cache.get(id);
    if (!url) { url = await elevenBlob(spoken); cache.set(id, url); }
    if (loading !== id) return "";   // arrêté pendant le chargement
    audio = new Audio(url);
    audio.onended = () => { if (playing === id) { playing = null; emit(); } };
    loading = null; playing = id; emit();
    await audio.play();
    return "";
  } catch (e: any) {
    loading = null; playing = null; emit();
    return e?.message || "Lecture impossible.";
  }
}

const VOCAL_KEY = "unic.vocalRate";
/** Vitesse de parole de UniC vocal : 1,25 par défaut (plus vif que la lecture des réponses écrites). */
export function getVocalRate(): number { try { const v = Number(localStorage.getItem(VOCAL_KEY)); return v >= 0.8 && v <= 1.6 ? v : 1.25; } catch { return 1.25; } }
export function setVocalRate(v: number): void { try { localStorage.setItem(VOCAL_KEY, String(Math.min(1.6, Math.max(0.8, v)))); } catch { /* ignoré */ } }

let elevenChain: Promise<void> = Promise.resolve();   // ElevenLabs : une voix après l'autre, mais le téléchargement de la phrase suivante démarre tout de suite

/** Une phrase dans la file : ne coupe pas ce qui est déjà en train d'être dit (parole au fil de l'eau). */
function sayQueued(text: string, rate = getVocalRate()): Promise<void> {
  return new Promise((resolve) => {
    const spoken = speakable(text);
    if (!spoken) return resolve();
    const pref = getPref();
    const device = () => {
      try {
        const synth = window.speechSynthesis;
        if (!synth || typeof SpeechSynthesisUtterance === "undefined") return resolve();
        const u = new SpeechSynthesisUtterance(spoken);
        u.lang = "fr-FR"; u.rate = rate;
        const v = deviceVoices().find((x) => x.voiceURI === pref.deviceVoice);
        if (v) u.voice = v;
        u.onend = () => resolve(); u.onerror = () => resolve();
        synth.speak(u);   // sans cancel() : la phrase précédente finit d'abord
      } catch { resolve(); }
    };
    if (pref.engine === "device") { device(); return; }
    const blob = elevenBlob(spoken);   // téléchargement lancé maintenant, lecture quand la phrase précédente est finie
    elevenChain = elevenChain.then(() => blob.then((url) => new Promise<void>((done) => {
      audio = new Audio(url);
      audio.playbackRate = rate;
      audio.onended = () => done(); audio.onerror = () => done();
      audio.play().catch(() => done());
    })).catch(() => {})).then(() => resolve());
  });
}

export function createSpeaker(): SpeechPipeline { stop(); elevenChain = Promise.resolve(); return new SpeechPipeline((t) => sayQueued(t), stop); }

/** Voix du téléphone pour une langue (« en-US », « ar-SA »…) : exacte d'abord, sinon même langue de base. */
export function voiceForLang(lang: string): SpeechSynthesisVoice | undefined {
  try {
    const l = lang.toLowerCase().replace("_", "-"), base = l.split("-")[0];
    const all = window.speechSynthesis?.getVoices() || [];
    return all.find((v) => v.lang.toLowerCase().replace("_", "-") === l) || all.find((v) => v.lang.toLowerCase().replace("_", "-").startsWith(base));
  } catch { return undefined; }
}

/** Dit une phrase dans une autre langue (interprète). Rend { voice: false } si le téléphone n'a pas de voix pour cette langue. */
export function sayIn(text: string, lang: string, rate = 1): Promise<{ voice: boolean }> {
  return new Promise((resolve) => {
    const spoken = speakable(text);
    if (!spoken) return resolve({ voice: true });
    const pref = getPref();
    if (pref.engine === "eleven") {   // voix ElevenLabs multilingue : lit n'importe quelle langue
      elevenBlob(spoken).then((url) => { stop(); audio = new Audio(url); audio.playbackRate = rate; audio.onended = () => resolve({ voice: true }); audio.onerror = () => resolve({ voice: true }); return audio.play(); })
        .catch(() => resolve({ voice: false }));
      return;
    }
    try {
      const synth = window.speechSynthesis;
      if (!synth || typeof SpeechSynthesisUtterance === "undefined") return resolve({ voice: false });
      synth.cancel();
      const u = new SpeechSynthesisUtterance(spoken);
      const v = voiceForLang(lang);
      u.lang = lang; u.rate = rate;
      if (v) u.voice = v;
      u.onend = () => resolve({ voice: !!v }); u.onerror = () => resolve({ voice: !!v });
      synth.speak(u);
    } catch { resolve({ voice: false }); }
  });
}

let ctx: AudioContext | null = null;
/** Petit « ding » discret : UniC a fini d'écouter, il réfléchit (retour immédiat, la réponse met parfois un instant). */
export function ding(freq = 880, vol = 0.06): void {
  try {
    ctx = ctx || new (window.AudioContext || (window as any).webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = freq; o.type = "sine";
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(vol, ctx.currentTime + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.14);
    o.connect(g).connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + 0.15);
  } catch { /* son indisponible : sans importance */ }
}

/** Lit un texte à voix haute et rend la main quand la lecture est finie (mode vocal : on enchaîne l'écoute). */
export function say(text: string, rate?: number): Promise<void> {
  return new Promise((resolve) => {
    const spoken = speakable(text);
    if (!spoken) return resolve();
    stop();
    const pref = getPref();
    const r = rate ?? pref.rate;
    const device = () => { try { if (!speakDevice(spoken, pref.deviceVoice, r, resolve)) resolve(); } catch { resolve(); } };
    if (pref.engine === "device") { device(); return; }
    elevenBlob(spoken).then((url) => {
      audio = new Audio(url);
      audio.playbackRate = r;
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
      audio.play().catch(() => resolve());
    }).catch(device);   // voix ElevenLabs indisponible : voix du téléphone
  });
}

export function clearCache(): void { cache.forEach((u) => URL.revokeObjectURL(u)); cache.clear(); }

export function useSpeech(id: string): "idle" | "loading" | "playing" {
  const [, tick] = useState(0);
  useEffect(() => { const l = () => tick((n) => n + 1); listeners.add(l); return () => { listeners.delete(l); }; }, []);
  return playing === id ? "playing" : loading === id ? "loading" : "idle";
}

export const canSpeakOnDevice = (): boolean => typeof window !== "undefined" && "speechSynthesis" in window;
export { isNative };
