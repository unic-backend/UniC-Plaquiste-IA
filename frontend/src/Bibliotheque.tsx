import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/**
 * Bibliothèque de savoir : les sources que le patron donne à l'IA (PDF, livres, documents de métier, liens) et ce qu'elle a
 * appris en cherchant. Elle s'appuie d'abord sur elles pour répondre, et dit lesquelles elle utilise.
 */
export function Bibliotheque() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  const load = useCallback(() => api.library().then((d) => setRows(d.sources)).catch((e) => setMsg(e?.message || "Erreur")), []);
  useEffect(() => { load(); }, [load]);
  const run = async (what: string, fn: () => Promise<any>, ok: (r: any) => string) => {
    setBusy(what); setMsg("");
    try { setMsg(ok(await fn())); await load(); } catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(""); }
  };
  const active = (rows || []).filter((r) => r.active);
  const retired = (rows || []).filter((r) => !r.active);
  const line = (r: any) => (
    <li key={r.id} className={r.active ? "" : "off"}>
      <span><b>{r.nom.replace(/^Savoir - /, "")}</b>
        <small> · {r.appris_par_ia ? "appris par l'IA" : "ta source"}{r.pages ? ` · ${r.pages} p.` : ""} · {r.passages} passage(s) · {r.date}</small>
        {r.erreur && <small className="error"> · {r.erreur}</small>}</span>
      <button className="btn btn-line btn-small" disabled={!!busy}
        onClick={() => run(r.id, () => api.libraryActive(r.id, !r.active), () => (r.active ? "Source retirée : elle reste gardée, l'IA ne la consulte plus." : "Source remise."))}>
        {r.active ? "Retirer" : "Remettre"}</button>
    </li>
  );
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Bibliothèque</h1>
        <p className="lede">Donne tes sources à l'IA : livres, PDF, normes, cours, documents de métier, liens. Elle les consulte en premier et dit lesquelles elle utilise.
          Ce qu'elle apprend en cherchant y est rangé aussi.</p>
        <section className="card-box lib-add">
          <button className="btn btn-copper" disabled={!!busy} onClick={() => ref.current?.click()}>{busy === "file" ? "Lecture…" : "Ajouter un fichier"}</button>
          <input ref={ref} type="file" hidden aria-label="Fichier à ajouter à la bibliothèque" accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
            onChange={(e) => {
              const f = e.target.files?.[0]; e.target.value = "";
              if (f) run("file", () => api.libraryAddFile(f), (r) => `« ${r.nom} » ajouté${r.pages ? ` (${r.pages} pages lues)` : ""}.`);
            }} />
          <div className="lib-url">
            <input type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… (article, page, guide)" aria-label="Lien à apprendre" />
            <button className="btn btn-line" disabled={!!busy || !/^https?:\/\/\S{4,}/.test(url.trim())}
              onClick={() => run("url", () => api.libraryAddUrl(url.trim()), (r) => { setUrl(""); return `Page apprise : ${r.titre}.`; })}>
              {busy === "url" ? "Lecture…" : "Apprendre ce lien"}</button>
          </div>
          <p className="hint">Un gros livre peut prendre une minute à lire. Le contenu d'Internet reste à vérifier avant une décision importante.</p>
        </section>
        {msg && <p className="hint" role="status">{msg}</p>}
        {!rows && <p className="hint">Chargement…</p>}
        {rows && !rows.length && <p className="hint">Bibliothèque vide : ajoute ta première source ci-dessus.</p>}
        {active.length > 0 && <><h3 className="cb-h">Sources consultées · {active.length}</h3><ul className="cb-exp-list lib-list">{active.map(line)}</ul></>}
        {retired.length > 0 && <><h3 className="cb-h">Retirées · {retired.length}</h3><ul className="cb-exp-list lib-list">{retired.map(line)}</ul></>}
      </div>
    </div>
  );
}
