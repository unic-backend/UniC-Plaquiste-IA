/** Markdown des réponses de l'IA → HTML sûr (tout le texte est échappé AVANT mise en forme ; seuls http(s), mailto et tel deviennent des liens). */

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const SAFE_URL = /^(https?:\/\/[^\s"'<>`]+|mailto:[^\s"'<>`]+|tel:[+\d][\d\s.-]*)$/i;

export function inline(src: string): string {
  const codes: string[] = [];
  // le code `…` est mis de côté : rien n'y est interprété
  let s = esc(src).replace(/`([^`]+)`/g, (_m, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  // [texte](adresse) : adresse contrôlée, jamais d'autre schéma (javascript:, data:…)
  s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, text, url) => SAFE_URL.test(url) ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>` : m);
  // adresse nue : ponctuation finale laissée hors du lien
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<>"'`]+?)([.,;:!?)]*)(?=\s|$)/g, (_m, pre, url, tail) => `${pre}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${tail}`);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*(?!\s)([^*]+?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/~~(.+?)~~/g, "<s>$1</s>");
  return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => `<code>${codes[+i]}</code>`);
}

const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/;
const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function md(text: string): string {
  const out: string[] = [];
  let list: "ul" | "ol" | null = null;
  let para: string[] = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br/>")}</p>`); para = []; } };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    // bloc de code ```
    if (/^\s*```/.test(line)) {
      flushPara(); closeList();
      const code: string[] = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      continue;
    }
    // tableau : une ligne d'en-tête, puis la ligne de séparation (---|---)
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      flushPara(); closeList();
      const head = cells(line);
      const rows: string[][] = [];
      for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim() !== ""; i++) rows.push(cells(lines[i]));
      i--;
      const td = (tag: "th" | "td", c: string) => `<${tag}>${inline(c)}</${tag}>`;
      out.push(`<div class="md-table"><table><thead><tr>${head.map((c) => td("th", c)).join("")}</tr></thead><tbody>` +
        rows.map((r) => `<tr>${head.map((_h, k) => td("td", r[k] ?? "")).join("")}</tr>`).join("") + `</tbody></table></div>`);
      continue;
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const num = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const head = /^#{1,4}\s+(.*)$/.exec(line);
    const quote = /^\s*>\s?(.*)$/.exec(line);
    if (bullet || num) {
      flushPara();
      const kind = bullet ? "ul" : "ol";
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline((bullet || num)![1])}</li>`);
    } else if (head) {
      flushPara(); closeList();
      out.push(`<h3>${inline(head[1])}</h3>`);
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flushPara(); closeList();
      out.push("<hr/>");
    } else if (quote) {
      flushPara(); closeList();
      const q: string[] = [quote[1]];
      while (i + 1 < lines.length && /^\s*>\s?/.test(lines[i + 1])) q.push(lines[++i].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${q.map(inline).join("<br/>")}</blockquote>`);
    } else if (!line.trim()) {
      flushPara(); closeList();
    } else {
      closeList();
      para.push(inline(line));
    }
  }
  flushPara(); closeList();
  return out.join("");
}
