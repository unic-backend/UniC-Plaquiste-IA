// Markdown des réponses : tableaux, liens sûrs, code, citations. Lancer : npm run test:phone
import { inline, md } from "../src/markdown";
let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };
const has = (l: string, h: string, n: string) => { const r = h.includes(n); (r ? ok++ : ko++); if (!r) console.log("ÉCHEC", l, "« " + n + " » absent de", h); };
const hasNot = (l: string, h: string, n: string) => { const r = !h.includes(n); (r ? ok++ : ko++); if (!r) console.log("ÉCHEC", l, "« " + n + " » présent dans", h); };

// tableau
const t = md("Voici :\n\n| Article | Qté |\n|---|---:|\n| Plaque BA13 | 24 |\n| Rail | 18 |\n\nFin.");
has("tableau en-tête", t, "<th>Article</th><th>Qté</th>");
has("tableau ligne 1", t, "<td>Plaque BA13</td><td>24</td>");
has("tableau ligne 2", t, "<td>Rail</td><td>18</td>");
has("tableau enveloppé pour défiler", t, '<div class="md-table"><table>');
has("paragraphes autour du tableau", t, "<p>Voici :</p>");
hasNot("plus de barres brutes", t, "|---");
has("ligne courte complétée", md("| a | b |\n|---|---|\n| 1 |"), "<td>1</td><td></td>");
has("tableau sans barres de bord", md("a | b\n--|--\n1 | 2"), "<td>1</td><td>2</td>");
eq("une seule barre sans séparateur n'est pas un tableau", md("Choisis A | B"), "<p>Choisis A | B</p>");

// sécurité
hasNot("HTML échappé", md("<script>alert(1)</script>"), "<script>");
hasNot("javascript: refusé", md("[clic](javascript:alert(1))"), "<a ");
hasNot("data: refusé", md("[clic](data:text/html;base64,AAAA)"), "<a ");
has("lien https", md("[site](https://www.unicplaquiste.com/book/)"), '<a href="https://www.unicplaquiste.com/book/" target="_blank" rel="noopener noreferrer">site</a>');
has("lien tel", md("[appeler](tel:+221777085092)"), 'href="tel:+221777085092"');
has("adresse nue, ponctuation hors lien", inline("Va sur https://exemple.sn/x."), 'href="https://exemple.sn/x" target="_blank" rel="noopener noreferrer">https://exemple.sn/x</a>.');
hasNot("guillemet dans l'adresse ne casse pas l'attribut", md('[x](https://a.sn/"onmouseover="alert(1))'), "<a ");
has("cellule échappée", md("| a |\n|---|\n| <img src=x onerror=alert(1)> |"), "&lt;img");

// code, citation, séparateur, mise en forme existante
has("code en ligne intact", inline("utilise `a*b*c`"), "<code>a*b*c</code>");
has("bloc de code échappé", md("```\n<b>x</b>\n```"), "<pre><code>&lt;b&gt;x&lt;/b&gt;</code></pre>");
has("citation", md("> note\n> suite"), "<blockquote>note<br/>suite</blockquote>");
has("séparateur", md("a\n\n---\n\nb"), "<hr/>");
has("gras", inline("**Total**"), "<strong>Total</strong>");
has("liste", md("- un\n- deux"), "<ul><li>un</li><li>deux</li></ul>");
has("liste numérotée", md("1. un\n2. deux"), "<ol><li>un</li><li>deux</li></ol>");
has("titre", md("## Titre"), "<h3>Titre</h3>");
eq("texte simple", md("Bonjour"), "<p>Bonjour</p>");
eq("vide", md(""), "");
// texte en cours de flux : tableau incomplet ne plante pas
has("flux : en-tête seul", md("| a | b |\n|---|"), "|---|");
console.log(`markdown : OK ${ok}  ÉCHECS ${ko}`);
if (ko) process.exit(1);
