#!/usr/bin/env python3
import re, base64, pathlib, markdown

DOCS = pathlib.Path("/home/ubuntu/dpf_testing_scenarios/docs")
SRC  = DOCS / "HBN_POD_VF_OFFLOAD_REFERENCE_ARCHITECTURE.md"
IMG  = DOCS / "images"
OUT  = pathlib.Path("/tmp/claude-1000/-home-ubuntu-dpf-testing-scenarios/e8d9803f-af84-4b02-ad6d-63ef7d0adee0/scratchpad")
OUT.mkdir(parents=True, exist_ok=True)

md_text = SRC.read_text()

# Drop the manual "Table of contents" block (we build our own; its GitHub-style
# anchors don't match python-markdown slugs).
md_text = re.sub(r"\n## Table of contents\n.*?\n---\n", "\n", md_text, count=1, flags=re.DOTALL)

# Split header (before "## 1.") from body.
m = re.search(r"\n## 1\. ", md_text)
head_md, body_md = md_text[:m.start()], md_text[m.start():]

def img_data_uri(path):
    b = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(b).decode()

def convert(src):
    md = markdown.Markdown(extensions=["tables","fenced_code","toc","attr_list","sane_lists"],
                           extension_configs={"toc":{"permalink":False}})
    html = md.convert(src)
    return html, getattr(md, "toc_tokens", [])

head_html, _ = convert(head_md)
# Drop the doc's own H1 (the masthead/cover already carries the title).
head_html = re.sub(r"<h1[^>]*>.*?</h1>", "", head_html, count=1, flags=re.DOTALL)
body_html, toc_tokens = convert(body_md)

# Inline images as data URIs.
def inline_imgs(html):
    def rep(mt):
        src = mt.group(1)
        name = src.split("/")[-1]
        p = IMG / name
        if p.exists():
            return 'src="%s"' % img_data_uri(p)
        return mt.group(0)
    return re.sub(r'src="(images/[^"]+)"', rep, html)
body_html = inline_imgs(body_html)

# Figure captions: <p><em>Figure ...</em></p> -> styled caption
body_html = re.sub(r'<p><em>(Figure[^<]*)</em></p>', r'<p class="figcap">\1</p>', body_html)

# Wrap tables and pre for horizontal scroll
body_html = body_html.replace("<table>", '<div class="scroll"><table>').replace("</table>", "</table></div>")

# Build TOC (level-2 sections) from tokens
def flatten(tokens, lvl2=None):
    items=[]
    for t in tokens:
        items.append(t)
        if t.get("children"):
            items += flatten(t["children"])
    return items
all_toks = flatten(toc_tokens)
sec2 = [t for t in all_toks if t["level"]==2]

def toc_nav():
    lis="".join('<li><a href="#%s"><span class="tn">%s</span>%s</a></li>' %
                (t["id"], t["name"].split(".")[0].strip(), t["name"].split(".",1)[1].strip() if "." in t["name"] else t["name"])
                for t in sec2)
    return '<nav class="toc" aria-label="Contents"><div class="toc-h">Contents</div><ol>%s</ol></nav>' % lis

def toc_pdf():
    rows=""
    for t in sec2:
        num=t["name"].split(".")[0].strip()
        title=t["name"].split(".",1)[1].strip() if "." in t["name"] else t["name"]
        rows+='<li><span class="tn">%s</span> %s</li>' % (num, title)
    return '<ol class="pdftoc">%s</ol>' % rows

CONTENT_CSS = r"""
:root{
  --bg:#ffffff; --surface:#f5f8f4; --surface-2:#eaefe8; --ink:#14181a;
  --ink-soft:#48524d; --ink-faint:#727c76; --rule:#e2e7e2; --rule-strong:#cfd6cf;
  --accent:#4e7d00; --accent-ink:#3c6100; --accent-wash:#eef4e2; --on-accent:#ffffff;
  --link:#1f6feb; --radius:9px;
  --font-sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --font-mono:ui-monospace,"SF Mono","DejaVu Sans Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0e1211; --surface:#161c19; --surface-2:#1d2420; --ink:#e7ece9;
  --ink-soft:#9ea8a2; --ink-faint:#79837d; --rule:#252c28; --rule-strong:#333b36;
  --accent:#9bd34a; --accent-ink:#b6e06f; --accent-wash:#1a2413; --on-accent:#0e1211;
  --link:#5aa2ff;
}}
:root[data-theme="light"]{
  --bg:#ffffff; --surface:#f5f8f4; --surface-2:#eaefe8; --ink:#14181a;
  --ink-soft:#48524d; --ink-faint:#727c76; --rule:#e2e7e2; --rule-strong:#cfd6cf;
  --accent:#4e7d00; --accent-ink:#3c6100; --accent-wash:#eef4e2; --on-accent:#ffffff; --link:#1f6feb;
}
:root[data-theme="dark"]{
  --bg:#0e1211; --surface:#161c19; --surface-2:#1d2420; --ink:#e7ece9;
  --ink-soft:#9ea8a2; --ink-faint:#79837d; --rule:#252c28; --rule-strong:#333b36;
  --accent:#9bd34a; --accent-ink:#b6e06f; --accent-wash:#1a2413; --on-accent:#0e1211; --link:#5aa2ff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-sans);
  line-height:1.65;-webkit-font-smoothing:antialiased;font-size:16px}
.content{max-width:78ch}
.content h1,.content h2,.content h3,.content h4{line-height:1.25;text-wrap:balance;color:var(--ink)}
.content h2{font-size:1.55rem;font-weight:650;margin:2.6rem 0 1rem;padding-top:1.4rem;
  border-top:1px solid var(--rule)}
.content h3{font-size:1.16rem;font-weight:640;margin:1.9rem 0 .6rem;color:var(--ink)}
.content h4{font-size:.98rem;font-weight:660;margin:1.4rem 0 .5rem}
.content p,.content li{color:var(--ink)}
.content p{margin:.75rem 0}
.content a{color:var(--link);text-decoration:none;border-bottom:1px solid transparent}
.content a:hover{border-bottom-color:currentColor}
.content strong{font-weight:660;color:var(--ink)}
.content ul,.content ol{padding-left:1.35rem;margin:.7rem 0}
.content li{margin:.3rem 0}
.content code{font-family:var(--font-mono);font-size:.86em;background:var(--surface-2);
  padding:.12em .38em;border-radius:5px}
.content pre{background:var(--surface);border:1px solid var(--rule);border-radius:var(--radius);
  padding:1rem 1.1rem;overflow-x:auto;margin:1rem 0}
.content pre code{background:none;padding:0;font-size:.83rem;line-height:1.55;white-space:pre}
.scroll{overflow-x:auto;margin:1.1rem 0;border:1px solid var(--rule);border-radius:var(--radius)}
.content table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
.content th,.content td{text-align:left;padding:.55rem .8rem;border-bottom:1px solid var(--rule);
  vertical-align:top}
.content thead th{background:var(--surface);color:var(--ink);font-weight:640;
  border-bottom:2px solid var(--rule-strong);position:sticky;top:0}
.content tbody tr:nth-child(even){background:color-mix(in srgb,var(--surface) 55%,transparent)}
.content img{display:block;margin:1.2rem auto .3rem;max-width:100%;height:auto;
  border:1px solid var(--rule);border-radius:var(--radius);background:#fff}
.content .figcap{text-align:center;font-size:.83rem;color:var(--ink-faint);
  font-style:italic;margin:.15rem auto 1.6rem;max-width:60ch}
.content blockquote{margin:1.1rem 0;padding:.7rem 1.05rem;background:var(--accent-wash);
  border-left:3px solid var(--accent);border-radius:0 var(--radius) var(--radius) 0;color:var(--ink)}
.content blockquote p{margin:.3rem 0}
.content hr{border:none;border-top:1px solid var(--rule);margin:2rem 0}
.content em{color:var(--ink-soft)}
"""

SHELL_CSS = r"""
.page{max-width:1180px;margin:0 auto;padding:0 clamp(16px,4vw,40px)}
.masthead{padding:2.6rem 0 1.6rem;border-bottom:1px solid var(--rule);margin-bottom:1.4rem}
.eyebrow{font-family:var(--font-mono);font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;
  color:var(--accent-ink);margin:0 0 .7rem}
.masthead h1{font-size:clamp(1.7rem,3.4vw,2.5rem);line-height:1.15;font-weight:680;margin:0 0 .8rem;
  text-wrap:balance;letter-spacing:-.01em}
.masthead .sub{color:var(--ink-soft);max-width:70ch;font-size:1.02rem;margin:0}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;margin:1.2rem 0 0}
.chip{font-family:var(--font-mono);font-size:.72rem;color:var(--ink-soft);background:var(--surface);
  border:1px solid var(--rule);border-radius:999px;padding:.28rem .7rem;letter-spacing:.02em}
.actions{margin-top:1.4rem}
.dl{display:inline-flex;align-items:center;gap:.5rem;font-family:var(--font-sans);font-size:.9rem;
  font-weight:600;color:var(--on-accent);background:var(--accent);border:1px solid var(--accent-ink);
  padding:.55rem 1rem;border-radius:8px;text-decoration:none}
.dl:hover{filter:brightness(1.05)}
.layout{display:grid;grid-template-columns:1fr;gap:2rem;align-items:start}
.toc{display:none}
.toc-h{font-family:var(--font-mono);font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;
  color:var(--ink-faint);margin:0 0 .7rem}
.toc ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.1rem}
.toc a{display:flex;gap:.55rem;align-items:baseline;color:var(--ink-soft);text-decoration:none;
  font-size:.85rem;line-height:1.3;padding:.28rem .4rem;border-radius:6px;border-bottom:none}
.toc a:hover{background:var(--surface);color:var(--ink)}
.toc .tn{font-family:var(--font-mono);font-size:.75rem;color:var(--accent-ink);min-width:1.1rem;text-align:right}
.footer{margin:3rem 0 2.5rem;padding-top:1.2rem;border-top:1px solid var(--rule);
  color:var(--ink-faint);font-size:.8rem}
@media(min-width:1000px){
  .layout{grid-template-columns:230px minmax(0,1fr)}
  .toc{display:block;position:sticky;top:1.4rem;max-height:calc(100vh - 2.8rem);overflow-y:auto;
    padding-right:.4rem}
}
"""

DOWNLOAD_BTN = "{DOWNLOAD_BTN}"  # placeholder, filled after PDF built

def artifact_body(pdf_b64):
    dl = ('<a class="dl" download="HBN-pod-VF-offload-reference-architecture.pdf" '
          'href="data:application/pdf;base64,%s">Download PDF</a>' % pdf_b64) if pdf_b64 else ""
    return f"""<style>{CONTENT_CSS}{SHELL_CSS}</style>
<div class="page">
  <header class="masthead">
    <p class="eyebrow">Reference Architecture</p>
    <h1>DOCA HBN Pod-VF Hardware Offload on BlueField-3</h1>
    <p class="sub">End-to-end design of a DPF Zero-Trust cluster running DOCA HBN (EVPN L2VNI) with pod-VF hardware eSwitch offload, delivered as Spectro Cloud Palette profiles on MaaS bare metal. For NVIDIA DOCA/DPF and Spectro Cloud field engineering.</p>
    <div class="chips">
      <span class="chip">DPF v25.10.1</span><span class="chip">DOCA HBN · BlueField-3</span>
      <span class="chip">OVN-Kubernetes</span><span class="chip">Spectro Palette / MaaS</span>
      <span class="chip">Kamaji tenant CP</span>
    </div>
    <div class="actions">{dl}</div>
  </header>
  <div class="layout">
    {toc_nav()}
    <main class="content">
      {head_html}
      {body_html}
      <p class="footer">Reference deployment: cluster <code>dpf-hbn-ovn-v28</code>, profiles infra v14 + HBN v28. Bandwidth aggregation 77.72 Gbit/s across both 40 GbE uplinks; DPU Arm 92.6% idle under load.</p>
    </main>
  </div>
</div>"""

# ---- PDF build (WeasyPrint) ----
PRINT_CSS = r"""
@page{size:A4;margin:16mm 15mm 18mm;
  @bottom-center{content:counter(page);font-family:'DejaVu Sans';font-size:8pt;color:#888}}
*{box-sizing:border-box}
body{font-family:'DejaVu Sans';color:#14181a;font-size:10pt;line-height:1.5}
.pdf-cover{margin-bottom:1.2rem;padding-bottom:1rem;border-bottom:2px solid #4e7d00}
.pdf-cover .eyebrow{font-family:'DejaVu Sans Mono';font-size:8pt;letter-spacing:.14em;
  text-transform:uppercase;color:#4e7d00;margin:0 0 .5rem}
.pdf-cover h1{font-size:19pt;line-height:1.18;margin:0 0 .5rem;color:#14181a}
.pdf-cover .sub{color:#48524d;font-size:10pt;margin:0;max-width:52em}
.pdf-cover .chips{margin-top:.7rem;font-family:'DejaVu Sans Mono';font-size:7.5pt;color:#727c76}
.pdftoc{list-style:none;margin:.4rem 0 1.4rem;padding:0;columns:2;column-gap:2rem}
.pdftoc li{margin:.18rem 0;break-inside:avoid;font-size:9pt;color:#14181a}
.pdftoc .tn{font-family:'DejaVu Sans Mono';color:#4e7d00}
h2{font-size:14pt;font-weight:bold;margin:1.3rem 0 .5rem;padding-top:.6rem;border-top:1px solid #e2e7e2;
  break-after:avoid}
h3{font-size:11.5pt;margin:1rem 0 .35rem;break-after:avoid}
h4{font-size:10pt;margin:.8rem 0 .3rem;break-after:avoid}
p{margin:.5rem 0}
a{color:#1f6feb;text-decoration:none}
code{font-family:'DejaVu Sans Mono';font-size:8.4pt;background:#eef2ec;padding:.05em .3em;border-radius:3px}
pre{background:#f5f8f4;border:1px solid #e2e7e2;border-radius:6px;padding:.7rem .8rem;overflow:hidden;
  break-inside:avoid;margin:.7rem 0}
pre code{background:none;padding:0;font-size:7.6pt;line-height:1.45;white-space:pre-wrap;word-break:break-word}
.scroll{margin:.7rem 0}
table{border-collapse:collapse;width:100%;font-size:8.4pt;break-inside:auto}
th,td{text-align:left;padding:.32rem .45rem;border-bottom:1px solid #e2e7e2;vertical-align:top}
thead th{background:#eef2ec;font-weight:bold;border-bottom:1.5px solid #cfd6cf}
tr{break-inside:avoid}
img{display:block;margin:.6rem auto .2rem;max-width:100%;break-inside:avoid;border:1px solid #e2e7e2;border-radius:5px}
.figcap{text-align:center;font-size:8pt;color:#727c76;font-style:italic;margin:.1rem auto .9rem}
blockquote{margin:.7rem 0;padding:.5rem .8rem;background:#eef4e2;border-left:3px solid #4e7d00;color:#14181a}
blockquote p{margin:.2rem 0}
hr{border:none;border-top:1px solid #e2e7e2;margin:1.2rem 0}
em{color:#48524d}
"""

pdf_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{PRINT_CSS}</style></head>
<body>
<div class="pdf-cover">
  <p class="eyebrow">Reference Architecture</p>
  <h1>DOCA HBN Pod-VF Hardware Offload on BlueField-3<br>via NVIDIA DPF and Spectro Cloud Palette</h1>
  <p class="sub">End-to-end design of a DPF Zero-Trust cluster running DOCA HBN (EVPN L2VNI) with pod-VF hardware eSwitch offload, delivered as Spectro Cloud Palette profiles on MaaS bare metal. For NVIDIA DOCA/DPF and Spectro Cloud field engineering.</p>
  <p class="chips">DPF v25.10.1 · DOCA HBN / BlueField-3 · OVN-Kubernetes · Spectro Palette / MaaS · Kamaji tenant CP</p>
</div>
<h2 style="border-top:none;padding-top:0">Contents</h2>
{toc_pdf()}
{head_html}
{body_html}
</body></html>"""

(OUT/"print.html").write_text(pdf_html)

from weasyprint import HTML
pdf_path = OUT/"HBN-pod-VF-offload-reference-architecture.pdf"
HTML(string=pdf_html, base_url=str(DOCS)).write_pdf(str(pdf_path))
print("PDF:", pdf_path, "%.2f MB" % (pdf_path.stat().st_size/1e6))

pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode()
art = artifact_body(pdf_b64)
(OUT/"reference-architecture.html").write_text(art)
print("Artifact HTML:", OUT/"reference-architecture.html", "%.2f MB" % ((OUT/'reference-architecture.html').stat().st_size/1e6))
print("sections in TOC:", len(sec2))
