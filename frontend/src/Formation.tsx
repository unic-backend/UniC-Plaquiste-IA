import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import * as I from "./Icons";
import { drawSketches } from "./sketchy";

/**
 * Formation UniC : un cours déjà écrit (règles du patron), des questions et des exercices corrigés par le moteur de calcul.
 * Aucune conversation avec l'IA, donc aucun crédit : ça marche même API coupée. Aucun prix montré.
 */
type Tab = "cours" | "questions" | "exercices" | "examen" | "suivi";
const TABS: [Tab, string][] = [["cours", "Cours"], ["questions", "Questions"], ["exercices", "Exercices"], ["examen", "Examen"], ["suivi", "Suivi"]];
const CONF = ["sûr", "pas sûr", "deviné"];
const WHO = "unic.formation.eleve";   // dernier prénom sur ce téléphone (confort)
const read = () => { try { return localStorage.getItem(WHO) || ""; } catch { return ""; } };
const qty = (n: number) => n.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
// « 13 barres », « 9 u » : seuls les mots prennent un s (comme Calcul par pièce)
const qtyUnit = (n: number, unit: string) => `${qty(n)} ${n > 1 && /^[a-zà-ÿ]{3,}$/i.test(unit) && !unit.endsWith("s") ? `${unit}s` : unit}`;
const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(/\s/g, "").replace(",", ".")));
const newSeed = () => Math.floor(Math.random() * 1e6);

export function Formation() {
  const [c, setC] = useState<any>(null);
  const [tab, setTab] = useState<Tab>("cours");
  const [eleve, setEleve] = useState(read);
  const [err, setErr] = useState("");
  useEffect(() => { api.formation().then(setC, (e) => setErr(e?.message || "Erreur")); }, []);
  useEffect(() => { try { localStorage.setItem(WHO, eleve); } catch { /* stockage indisponible */ } }, [eleve]);
  const who = eleve.trim();
  return (
    <div className="page">
      <div className="page-inner mat">
        <h1>Formation UniC</h1>
        <p className="lede">Le cours du plaquiste UniC, prêt à étudier. Corrigé par le moteur de calcul : sans l'IA, sans crédit.</p>
        <label className="fo-who">Élève
          <input value={eleve} maxLength={40} list="fo-eleves" placeholder="Prénom" onChange={(e) => setEleve(e.target.value)} />
          <datalist id="fo-eleves">{(c?.eleves || []).map((n: string) => <option key={n} value={n} />)}</datalist>
        </label>
        <div className="seg fo-tabs" role="tablist" aria-label="Parties du cours">
          {TABS.map(([t, label]) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{label}</button>
          ))}
        </div>
        {err && <p className="error" role="alert">{err}</p>}
        {!c ? !err && <p className="hint">Chargement…</p>
          : tab !== "cours" && !who ? <p className="hint">Écris le prénom de l'élève pour garder sa progression.</p>
          : tab === "cours" ? <Cours c={c} who={who} />
          : tab === "questions" ? <Questions c={c} who={who} />
          : tab === "exercices" ? <Exercice key="ex" who={who} exam={false} />
          : tab === "examen" ? <Exercice key="exam" who={who} exam />
          : <Suivi who={who} c={c} />}
      </div>
    </div>
  );
}

function useRun() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setErr("");
    try { await fn(); } catch (e: any) { setErr(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  return { busy, err, run };
}

function Cours({ c, who }: { c: any; who: string }) {
  const { busy, err, run } = useRun();
  const [done, setDone] = useState<string[]>([]);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (who) api.formationSuivi(who).then((p) => setDone(p.lecons), () => {}); }, [who]);
  useEffect(() => { drawSketches(box.current); }, [c]);
  return (
    <div className="mat-list" ref={box}>
      {c.modules.map((m: any) => (
        <section key={m.id} className="mat-row fo-mod">
          <div className="mat-head"><b>{m.titre}</b>{done.includes(m.id) && <span className="fo-ok"><I.Check size={14} /> compris</span>}</div>
          <ul>{m.points.map((p: string) => <li key={p}>{p}</li>)}</ul>
          {m.pieges.length > 0 && <p className="fo-trap"><b>Piège :</b> {m.pieges.join(" ")}</p>}
          {m.croquis && <div className="sketchy fo-sketch" data-scene={m.croquis} dangerouslySetInnerHTML={{ __html: "" }} />}
          {m.exemple && (
            <details className="pc-why" open>
              <summary>Exemple résolu : {m.exemple.enonce}</summary>
              <ul>{m.exemple.resultat.map((r: any) => <li key={r.question}><b>{r.question} {qty(r.quantite)}</b> — {r.calcul}</li>)}</ul>
            </details>
          )}
          {who && !done.includes(m.id) && (
            <button className="btn btn-line" disabled={busy}
              onClick={() => run(async () => setDone((await api.formationLecon(who, m.id)).lecons))}>J'ai compris</button>
          )}
        </section>
      ))}
      {!who && <p className="hint">Écris un prénom pour cocher les leçons comprises.</p>}
      {err && <p className="error" role="alert">{err}</p>}
    </div>
  );
}

function Questions({ c, who }: { c: any; who: string }) {
  const { busy, err, run } = useRun();
  const [order, setOrder] = useState<string[] | null>(null);
  const [i, setI] = useState(0);
  const [pick, setPick] = useState<number | null>(null);
  const [res, setRes] = useState<any>(null);
  useEffect(() => {   // d'abord ce qui est à revoir, puis le reste
    api.formationSuivi(who).then((p) => {
      const ids = c.quiz.map((q: any) => q.id);
      setOrder([...p.a_revoir, ...ids.filter((id: string) => !p.a_revoir.includes(id))]);
    }, () => setOrder(c.quiz.map((q: any) => q.id)));
  }, [who, c]);
  if (!order) return <p className="hint">Chargement…</p>;
  if (i >= order.length) return <section className="mat-row"><p><b>Série finie.</b> Les réponses fausses, « pas sûr » ou « deviné » reviennent dans 2 jours.</p>
    <button className="btn btn-copper" onClick={() => { setI(0); setPick(null); setRes(null); }}>Recommencer</button></section>;
  const q = c.quiz.find((x: any) => x.id === order[i]);
  const answer = (conf: string) => run(async () => setRes(await api.formationQuiz(who, q.id, pick!, conf)));
  return (
    <section className="mat-row fo-q" aria-live="polite">
      <div className="mat-head"><b>Question {i + 1} / {order.length}</b></div>
      <p className="fo-ask">{q.q}</p>
      <div className="fo-choices">
        {q.choix.map((ch: string, k: number) => (
          <button key={ch} type="button" disabled={!!res} aria-pressed={pick === k}
            className={`btn ${res ? (ch === res.bonne ? "fo-good" : pick === k ? "fo-bad" : "btn-line") : pick === k ? "btn-copper" : "btn-line"}`}
            onClick={() => setPick(k)}>{ch}</button>
        ))}
      </div>
      {pick !== null && !res && (
        <><p className="hint">Tu es…</p>
          <div className="seg" role="group" aria-label="Certitude">
            {CONF.map((cf) => <button key={cf} type="button" disabled={busy} onClick={() => answer(cf)}>{cf}</button>)}
          </div></>
      )}
      {res && (
        <><p className={res.ok ? "hint ic" : "error"}>{res.ok ? <><I.Check size={16} /> Juste.</> : <>Faux. Bonne réponse : {res.bonne}.</>} {res.pourquoi}</p>
          <button className="btn btn-copper" onClick={() => { setI(i + 1); setPick(null); setRes(null); }}>Question suivante</button></>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}

function Exercice({ who, exam }: { who: string; exam: boolean }) {
  const { busy, err, run } = useRun();
  const [typ, setTyp] = useState(exam ? (Math.random() < 0.5 ? "plafond" : "cloison") : "plafond");
  const [seed, setSeed] = useState(newSeed);
  const [ex, setEx] = useState<any>(null);
  const [rep, setRep] = useState<Record<string, string>>({});
  const [hint, setHint] = useState<string[]>([]);
  const [res, setRes] = useState<any>(null);
  useEffect(() => { setEx(null); setRep({}); setHint([]); setRes(null); run(async () => setEx(await api.formationExercice(typ, seed))); }, [typ, seed]);
  const corriger = () => run(async () => {
    const reponses = Object.fromEntries(ex.questions.map((q: any) => [q.sku, num(rep[q.sku] || "")]));
    setRes(await api.formationCorriger({ eleve: who, type: typ, seed, reponses, examen: exam }));
  });
  return (
    <section className="mat-row fo-ex" aria-live="polite">
      {exam ? <p className="hint">Examen : aucune aide avant ta réponse. Note : refaire, plus dur ou tâche complète.</p> : (
        <div className="seg" role="group" aria-label="Type d'exercice">
          {[["plafond", "Faux plafond"], ["cloison", "Cloison"]].map(([v, label]) => (
            <button key={v} type="button" className={typ === v ? "on" : ""} aria-pressed={typ === v} onClick={() => setTyp(v)}>{label}</button>
          ))}
        </div>
      )}
      {ex && (
        <form onSubmit={(e) => { e.preventDefault(); corriger(); }}>
          <p className="fo-ask">{ex.enonce}</p>
          {ex.questions.map((q: any) => {
            const l = res?.lignes.find((x: any) => x.sku === q.sku);
            return (
              <div key={q.sku} className="fo-line">
                <label>{q.question}
                  <input inputMode="decimal" value={rep[q.sku] || ""} disabled={!!res} onChange={(e) => setRep({ ...rep, [q.sku]: e.target.value })} />
                </label>
                {!exam && !res && !hint.includes(q.sku) && <button type="button" className="btn btn-line fo-hint" onClick={() => setHint([...hint, q.sku])}>Indice</button>}
                {!res && hint.includes(q.sku) && <p className="hint">{q.indice}</p>}
                {l && <p className={l.ok ? "hint ic" : "error"}>{l.ok ? <><I.Check size={14} /> Juste.</> : <>Attendu : {qtyUnit(l.attendu, l.unite)}.</>} {l.calcul}</p>}
              </div>
            );
          })}
          {!res ? <button type="submit" className="btn btn-copper" disabled={busy}>{busy ? "Correction…" : "Corriger"}</button> : (
            <><p className="fo-score"><b>{res.bon} / {res.total}</b> ({res.pourcent} %) : {res.verdict}</p>
              <button type="button" className="btn btn-copper" onClick={() => { if (exam) setTyp(Math.random() < 0.5 ? "plafond" : "cloison"); setSeed(newSeed()); }}>
                {exam ? "Nouvel examen" : "Nouvel exercice"}</button></>
          )}
        </form>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}

function Suivi({ who, c }: { who: string; c: any }) {
  const [p, setP] = useState<any>(null);
  useEffect(() => { api.formationSuivi(who).then(setP, () => setP(null)); }, [who]);
  if (!p) return <p className="hint">Chargement…</p>;
  const titre = (id: string) => c.quiz.find((q: any) => q.id === id)?.q || id;
  return (
    <section className="mat-row fo-suivi">
      <div className="mat-head"><b>Fiche de suivi : {p.eleve}</b></div>
      <ul>
        <li>Leçons comprises : {p.lecons.length} / {p.total_lecons}</li>
        <li>Questions : {p.quiz_justes} justes sur {p.quiz_faits} faites ({p.total_quiz} au total)</li>
        <li>Exercices faits : {p.exercices}</li>
        <li>Dernier examen : {p.dernier_examen ? `${p.dernier_examen.bon} / ${p.dernier_examen.total} (${p.dernier_examen.type})` : "pas encore"}</li>
      </ul>
      {p.a_revoir.length > 0 && <><p><b>À revoir aujourd'hui :</b></p><ul>{p.a_revoir.map((id: string) => <li key={id}>{titre(id)}</li>)}</ul></>}
      {p.derniers.length > 0 && (
        <details className="pc-why"><summary>Derniers exercices</summary>
          <ul>{p.derniers.map((e: any, k: number) => <li key={k}>{e.at.slice(0, 10)} · {e.type}{e.examen ? " (examen)" : ""} : {e.bon} / {e.total}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
