// src/markdown.ts
var esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
var SAFE_URL = /^(https?:\/\/[^\s"'<>`]+|mailto:[^\s"'<>`]+|tel:[+\d][\d\s.-]*)$/i;
function inline(src) {
  const codes = [];
  let s = esc(src).replace(/`([^`]+)`/g, (_m, c) => {
    codes.push(c);
    return `\0${codes.length - 1}\0`;
  });
  s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, text, url) => SAFE_URL.test(url) ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>` : m);
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<>"'`]+?)([.,;:!?)]*)(?=\s|$)/g, (_m, pre, url, tail) => `${pre}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${tail}`);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*(?!\s)([^*]+?)\*(?!\*)/g, "$1<em>$2</em>").replace(/~~(.+?)~~/g, "<s>$1</s>");
  return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => `<code>${codes[+i]}</code>`);
}
var TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/;
var cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
function md(text) {
  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${para.join("<br/>")}</p>`);
      para = [];
    }
  };
  const closeList = () => {
    if (list) {
      out.push(`</${list}>`);
      list = null;
    }
  };
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    if (/^\s*```/.test(line)) {
      flushPara();
      closeList();
      const code = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      flushPara();
      closeList();
      const head2 = cells(line);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim() !== ""; i++) rows.push(cells(lines[i]));
      i--;
      const td = (tag, c) => `<${tag}>${inline(c)}</${tag}>`;
      out.push(`<div class="md-table"><table><thead><tr>${head2.map((c) => td("th", c)).join("")}</tr></thead><tbody>` + rows.map((r) => `<tr>${head2.map((_h, k) => td("td", r[k] ?? "")).join("")}</tr>`).join("") + `</tbody></table></div>`);
      continue;
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const num = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const head = /^#{1,4}\s+(.*)$/.exec(line);
    const quote = /^\s*>\s?(.*)$/.exec(line);
    if (bullet || num) {
      flushPara();
      const kind = bullet ? "ul" : "ol";
      if (list !== kind) {
        closeList();
        out.push(`<${kind}>`);
        list = kind;
      }
      out.push(`<li>${inline((bullet || num)[1])}</li>`);
    } else if (head) {
      flushPara();
      closeList();
      out.push(`<h3>${inline(head[1])}</h3>`);
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flushPara();
      closeList();
      out.push("<hr/>");
    } else if (quote) {
      flushPara();
      closeList();
      const q = [quote[1]];
      while (i + 1 < lines.length && /^\s*>\s?/.test(lines[i + 1])) q.push(lines[++i].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${q.map(inline).join("<br/>")}</blockquote>`);
    } else if (!line.trim()) {
      flushPara();
      closeList();
    } else {
      closeList();
      para.push(inline(line));
    }
  }
  flushPara();
  closeList();
  return out.join("");
}

// tests/markdown.check.ts
var ok = 0;
var ko = 0;
var eq = (l, g, w) => {
  const a = JSON.stringify(g), b = JSON.stringify(w);
  a === b ? ok++ : ko++;
  if (a !== b) console.log("\xC9CHEC", l, a, "\u2260", b);
};
var has = (l, h, n) => {
  const r = h.includes(n);
  r ? ok++ : ko++;
  if (!r) console.log("\xC9CHEC", l, "\xAB " + n + " \xBB absent de", h);
};
var hasNot = (l, h, n) => {
  const r = !h.includes(n);
  r ? ok++ : ko++;
  if (!r) console.log("\xC9CHEC", l, "\xAB " + n + " \xBB pr\xE9sent dans", h);
};
var t = md("Voici :\n\n| Article | Qt\xE9 |\n|---|---:|\n| Plaque BA13 | 24 |\n| Rail | 18 |\n\nFin.");
has("tableau en-t\xEAte", t, "<th>Article</th><th>Qt\xE9</th>");
has("tableau ligne 1", t, "<td>Plaque BA13</td><td>24</td>");
has("tableau ligne 2", t, "<td>Rail</td><td>18</td>");
has("tableau envelopp\xE9 pour d\xE9filer", t, '<div class="md-table"><table>');
has("paragraphes autour du tableau", t, "<p>Voici :</p>");
hasNot("plus de barres brutes", t, "|---");
has("ligne courte compl\xE9t\xE9e", md("| a | b |\n|---|---|\n| 1 |"), "<td>1</td><td></td>");
has("tableau sans barres de bord", md("a | b\n--|--\n1 | 2"), "<td>1</td><td>2</td>");
eq("une seule barre sans s\xE9parateur n'est pas un tableau", md("Choisis A | B"), "<p>Choisis A | B</p>");
hasNot("HTML \xE9chapp\xE9", md("<script>alert(1)</script>"), "<script>");
hasNot("javascript: refus\xE9", md("[clic](javascript:alert(1))"), "<a ");
hasNot("data: refus\xE9", md("[clic](data:text/html;base64,AAAA)"), "<a ");
has("lien https", md("[site](https://www.unicplaquiste.com/book/)"), '<a href="https://www.unicplaquiste.com/book/" target="_blank" rel="noopener noreferrer">site</a>');
has("lien tel", md("[appeler](tel:+221777085092)"), 'href="tel:+221777085092"');
has("adresse nue, ponctuation hors lien", inline("Va sur https://exemple.sn/x."), 'href="https://exemple.sn/x" target="_blank" rel="noopener noreferrer">https://exemple.sn/x</a>.');
hasNot("guillemet dans l'adresse ne casse pas l'attribut", md('[x](https://a.sn/"onmouseover="alert(1))'), "<a ");
has("cellule \xE9chapp\xE9e", md("| a |\n|---|\n| <img src=x onerror=alert(1)> |"), "&lt;img");
has("code en ligne intact", inline("utilise `a*b*c`"), "<code>a*b*c</code>");
has("bloc de code \xE9chapp\xE9", md("```\n<b>x</b>\n```"), "<pre><code>&lt;b&gt;x&lt;/b&gt;</code></pre>");
has("citation", md("> note\n> suite"), "<blockquote>note<br/>suite</blockquote>");
has("s\xE9parateur", md("a\n\n---\n\nb"), "<hr/>");
has("gras", inline("**Total**"), "<strong>Total</strong>");
has("liste", md("- un\n- deux"), "<ul><li>un</li><li>deux</li></ul>");
has("liste num\xE9rot\xE9e", md("1. un\n2. deux"), "<ol><li>un</li><li>deux</li></ol>");
has("titre", md("## Titre"), "<h3>Titre</h3>");
eq("texte simple", md("Bonjour"), "<p>Bonjour</p>");
eq("vide", md(""), "");
has("flux : en-t\xEAte seul", md("| a | b |\n|---|"), "|---|");
console.log(`markdown : OK ${ok}  \xC9CHECS ${ko}`);
if (ko) process.exit(1);
