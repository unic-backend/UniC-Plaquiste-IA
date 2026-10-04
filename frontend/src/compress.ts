/** Allège un fichier AVANT l'envoi : photos réduites, gros PDF transformés en images de leurs premières pages.
 *  Le serveur (512 Mo) et la 4G n'ont plus à digérer un plan de 40 Mo. Jamais bloquant : en cas d'échec, le fichier part tel quel. */

const IMG_MAX_SIDE = 2400;
const IMG_QUALITY = 0.82;
const IMG_KEEP_BYTES = 600 * 1024;   // en dessous : déjà léger
const PDF_KEEP_BYTES = 8 * 1024 * 1024;   // en dessous : on garde le PDF (texte et cotes exacts)
const PDF_MAX_PAGES = 6;

export type Prepared = { files: File[]; note: string };

const baseName = (n: string) => n.replace(/\.[^.]+$/, "");
const mb = (n: number) => (n / 1048576).toFixed(1);

function toJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((ok, ko) => canvas.toBlob((b) => (b ? ok(b) : ko(new Error("jpeg"))), "image/jpeg", IMG_QUALITY));
}

async function shrinkImage(file: File): Promise<Prepared> {
  try {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, IMG_MAX_SIDE / Math.max(bmp.width, bmp.height));
    if (k === 1 && file.size <= IMG_KEEP_BYTES) { bmp.close(); return { files: [file], note: "" }; }
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k);
    c.height = Math.round(bmp.height * k);
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#fff";   // les PNG transparents deviendraient noirs en JPEG
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close();
    const blob = await toJpeg(c);
    if (blob.size >= file.size) return { files: [file], note: "" };
    return { files: [new File([blob], baseName(file.name) + ".jpg", { type: "image/jpeg" })], note: `${file.name} : ${mb(file.size)} → ${mb(blob.size)} Mo` };
  } catch {
    return { files: [file], note: "" };
  }
}

async function shrinkPdf(file: File): Promise<Prepared> {
  try {
    const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
    const worker = (await import("pdfjs-dist/legacy/build/pdf.worker.min.mjs?url")).default;
    pdfjs.GlobalWorkerOptions.workerSrc = worker;
    const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
    const n = Math.min(doc.numPages, PDF_MAX_PAGES);
    const out: File[] = [];
    for (let i = 1; i <= n; i++) {
      const page = await doc.getPage(i);
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: Math.min(3, IMG_MAX_SIDE / Math.max(base.width, base.height)) });
      const c = document.createElement("canvas");
      c.width = Math.round(viewport.width);
      c.height = Math.round(viewport.height);
      const ctx = c.getContext("2d")!;
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, c.width, c.height);
      await page.render({ canvasContext: ctx, viewport }).promise;
      out.push(new File([await toJpeg(c)], `${baseName(file.name)}-p${i}.jpg`, { type: "image/jpeg" }));
      page.cleanup();
    }
    await doc.destroy();
    const size = out.reduce((s, f) => s + f.size, 0);
    if (!out.length || size >= file.size) return { files: [file], note: "" };
    const cut = doc.numPages > n ? ` (${n} premières pages sur ${doc.numPages})` : "";
    return { files: out, note: `${file.name} : ${mb(file.size)} Mo → ${out.length} image(s), ${mb(size)} Mo${cut}` };
  } catch {
    return { files: [file], note: "" };
  }
}

export async function prepareFile(file: File): Promise<Prepared> {
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (isPdf) return file.size > PDF_KEEP_BYTES ? shrinkPdf(file) : { files: [file], note: "" };
  if (/^image\/(jpeg|png|webp|heic|heif)$/i.test(file.type)) return shrinkImage(file);
  return { files: [file], note: "" };
}
