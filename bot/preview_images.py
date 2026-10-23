"""Generate a reviewable, resumable Qwen image gallery without sending anything to WordPress."""
import html
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

import config
import generated_images


OUT = config.WORKSPACE_DIR / "output" / "qwen-approved-styles"
CONCEPTS = [
    ("Thumbnail YouTube heboh",
     "A spectacular Indonesian YouTube tech thumbnail about batch plotting CAD drawings. Close-up of an expressive young adult Indonesian male engineer, "
     "huge incredulous eyes, face occupies the left third. A tornado of white technical drawings overwhelms the red chaotic left background. "
     "On the electric lime-green right, a giant single mouse click sends the same drawings into a perfectly aligned floating fan. "
     "Extreme perspective, crisp photographic cutout, thick white subject outline, punchy graphic arrow, vivid red versus lime. "
     "Giant perfectly legible bold headline PLOT SATU-SATU? at the top and SEKALIGUS! lower right. Text is essential. "
     "Exaggerated entertaining visual metaphor, professional thumbnail craft. No desk, no monitor hero, no printer."),
    ("Editorial surealis",
     "Award-winning conceptual magazine cover, sophisticated surreal editorial photomontage about organizing many CAD drawing sheets into one batch. "
     "A giant sculptural cobalt-blue hand suspended in a warm ivory void catches a chaotic cloud of architectural drawings and transforms them into "
     "a precise folded paper staircase rising diagonally into a small architectural doorway. The paper itself contains delicate floor-plan linework. "
     "Unexpected scale, extreme negative space, hard midday shadows, tactile matte paper, a single vermilion circle, art-directed luxury editorial. "
     "No typography, no desk, no screen, no plotter, no traditional workstation."),
    ("Fotografi dokumenter",
     "Authentic cinematic documentary photograph for an engineering magazine. Tight overhead-and-oblique close shot of two Indonesian architects' "
     "hands collaborating over a sprawling full-size building floor plan in a real architecture studio. One hand holds a yellow pencil marking "
     "the drawing, another lifts a translucent tracing-paper layer. Faces mostly outside frame, tactile paper fibers, slightly worn wooden workbench, "
     "sunlight through blinds, real imperfections, editorial 35mm film grain, shallow focus on the hand and drawing, beautiful muted olive and amber. "
     "Make this feel like a real candid photograph. No screens, no printer, no text overlay, no synthetic 3D look."),
    ("Sketsa arsitektur liar",
     "Expressive architectural concept sketch filling the full canvas: a modern tropical Indonesian house bursts apart in an energetic exploded "
     "axonometric drawing, roof, walls, structural frame and floor plans floating in separate layers. Fierce confident black ink lines, rough graphite "
     "construction lines, loose orange marker strokes and cobalt watercolor splashes on warm cream sketchbook paper. A small hand-drawn curved arrow "
     "ties loose drawing sheets into one visual sequence at the bottom. Artistic, imperfect, architectural student competition-board energy. "
     "Not a photorealistic render. No desk, computer or printer, no legible text."),
    ("Poster tipografi brutalist",
     "Bold Swiss brutalist typographic poster for a CAD batch-plot article. ENORMOUS ultra-condensed black sans-serif typography reading "
     "PLOT on line one and SEKALIGUS on line two, typography occupies 70 percent of the entire canvas, words perfectly spelled and readable. "
     "Hot coral background, electric cobalt rectangular accents, layered torn architectural floor-plan paper strips cutting diagonally behind "
     "the letters, rigid asymmetric editorial grid, small black registration crosses, strong visual rhythm. Flat graphic design, "
     "museum-quality contemporary design poster, deliberately loud. No monitor, no printer, no photographs, no extra words or logos."),
    ("Pabrik gambar mini 3D",
     "Delightful miniature isometric automated paper factory, a playful metaphor for batch plotting CAD drawings. A single huge cobalt-blue "
     "button at one end feeds a beautifully intricate conveyor system where tiny orange industrial robot arms sort, align and stack white "
     "architectural drawing sheets. Conveyor runs in a bold S curve around a tiny architectural model in the center. Entire factory isolated "
     "on vivid butter-yellow background. Premium toy-like 3D rendering, matte resin, precise geometric forms, soft studio shadows, "
     "unexpected scale contrasts. No screens, no traditional printer, no desk, no words, no labels."),
    ("Origami sinematik",
     "Surreal cinematic advertising photograph, a breathtaking architectural fantasy made from paper drawings. A gigantic white origami bird "
     "with fine cobalt architectural floor-plan linework printed across its folded wings glides through a monumental concrete hall. "
     "Dozens of small technical drawing sheets follow it as an orderly flock, an elegant metaphor for one coordinated batch of drawings. "
     "Very wide low camera angle, one tiny human silhouette for scale, volumetric sunlight shafts, deep sculptural shadows, "
     "rich blue-white-bronze palette, premium luxury campaign aesthetic. No lettering, no computers, no desk, no plotter."),
    ("Papercut kota dari denah",
     "Exquisite tactile handcrafted paper-cut artwork, photographed top down. Architectural floor plans on flat cream paper transform progressively "
     "across the composition into a little three-dimensional Indonesian urban neighborhood, folded houses, tiny tropical trees, stepped rooftops "
     "and road strips. The transformation moves diagonally from black-line 2D drawings bottom-left to vibrant coral-and-cobalt paper buildings "
     "top-right. A giant circular cutout frames the miniature city. Layered paper edges visibly textured, beautifully cast crisp shadows, "
     "warm ivory backdrop, sophisticated book-cover composition, playful handmade imperfections. No words, no computer, no printer, no desk scene."),
]


def valid(path):
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def make_one(index):
    label, concept = CONCEPTS[index - 1]
    path = OUT / ("%02d.png" % index)
    prompt = (concept + " Landscape 16:9 editorial article cover. Commit fully to the specified medium and concept. "
              "No brand logos, no watermarks, no fabricated performance statistics. This is a conceptual illustration, not evidence of real customer outcomes.")
    if not valid(path):
        generated_images.generate(prompt, path)
    print("READY %02d %s" % (index, label), flush=True)
    return {"number": index, "style": label, "file": path.name, "prompt": prompt,
            "model": config.QWEN_IMAGE_MODEL}


def gallery(records):
    records = sorted(records, key=lambda item: item["number"])
    (OUT / "prompts.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 23) if font_path.exists() else ImageFont.load_default()
    grid = Image.new("RGB", (1200, ((len(records) + 1) // 2) * 380), "#eeeeee")
    draw = ImageDraw.Draw(grid)
    cards = []
    for position, record in enumerate(records):
        x, y = position % 2 * 600, position // 2 * 380
        with Image.open(OUT / record["file"]) as source:
            preview = ImageOps.contain(source.convert("RGB"), (588, 330))
            grid.paste(preview, (x + 6, y + 6))
        title = "%02d. %s" % (record["number"], record["style"])
        draw.text((x + 12, y + 342), title, fill="#111111", font=font)
        cards.append('<figure><a href="%s"><img src="%s" alt="%s"></a><figcaption>%s</figcaption></figure>' %
                     (record["file"], record["file"], html.escape(title), html.escape(title)))
    grid.save(OUT / "pilihan.jpg", quality=92)
    (OUT / "index.html").write_text(
        '<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Gaya Qwen pilihan — Smart Plot</title><style>body{margin:0;padding:32px;font:17px system-ui;background:#f4f3ef;color:#202020}'
        'main{max-width:1400px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}'
        'figure{margin:0;background:white;border-radius:12px;overflow:hidden}img{display:block;width:100%;height:auto}'
        'figcaption{padding:16px;font-weight:650}p{line-height:1.6}</style><main><h1>Pilih gaya gambar artikel</h1>'
        '<p>Smart Plot ZWCAD: mencetak banyak gambar kerja. Semua kandidat dibuat melalui API Qwen. Klik gambar untuk melihat ukuran penuh.</p>'
        '<section class="grid">' + "".join(cards) + '</section></main></html>', encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Validate the actual API before committing to the remaining nine calls.
    records = [make_one(1)]
    gallery(records)
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(make_one, i): i for i in range(2, len(CONCEPTS) + 1)}
        for future in as_completed(futures):
            try:
                records.append(future.result())
                gallery(records)
            except Exception as exc:
                errors.append({"number": futures[future], "error": str(exc)[:300]})
                print("FAILED %02d %s" % (futures[future], type(exc).__name__), flush=True)
    (OUT / "errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    print("GALLERY %d/%d %s" % (len(records), len(CONCEPTS), OUT), flush=True)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
