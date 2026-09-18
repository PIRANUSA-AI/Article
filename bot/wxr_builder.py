import datetime as dt
import html
import json
import re
import zipfile
from pathlib import Path

import config
import site_links

SUMMARY_HEADINGS = {"video": "Ringkasan video", "image": "Ringkasan", "text": "Ringkasan"}


def _now():
    value = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _iso(value):
    parsed = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _esc(text):
    return html.escape(str(text or ""), quote=True)


def _cd(text):
    return "<![CDATA[%s]]>" % str(text or "").replace("]]>", "]]]]><![CDATA[>")


def _link(match):
    label, url = match.group(1), html.unescape(match.group(2))
    if site_links.is_internal(url):
        return '<a href="%s">%s</a>' % (_esc(url), label)
    return '<a href="%s" target="_blank" rel="noreferrer noopener">%s</a>' % (_esc(url), label)


def _inline(text):
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text or ""))
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"\[([^\]\n]{1,120})\]\((https?://[^)\s]+)\)", _link, text)


def _attrs(data):
    return (" " + json.dumps(data, ensure_ascii=False, separators=(",", ":"))) if data else ""


def _paragraph(text, class_name=None, font_size=None, italic=False):
    attrs = {}
    classes = []
    if class_name:
        attrs["className"] = class_name
        classes.append(class_name)
    if font_size:
        attrs["fontSize"] = font_size
        classes.append("has-%s-font-size" % font_size)
    body = _inline(text)
    if italic:
        body = "<em>%s</em>" % body
    class_attr = ' class="%s"' % " ".join(classes) if classes else ""
    return "<!-- wp:paragraph%s -->\n<p%s>%s</p>\n<!-- /wp:paragraph -->" % (_attrs(attrs), class_attr, body)


def _heading(text, level=2):
    attrs = {} if level == 2 else {"level": level}
    return '<!-- wp:heading%s -->\n<h%d class="wp-block-heading">%s</h%d>\n<!-- /wp:heading -->' % (_attrs(attrs), level, _inline(text), level)


def _list(items, ordered=False):
    tag = "ol" if ordered else "ul"
    inner = "".join("<!-- wp:list-item -->\n<li>%s</li>\n<!-- /wp:list-item -->" % _inline(item) for item in items)
    attrs = {"ordered": True} if ordered else {}
    return '<!-- wp:list%s -->\n<%s class="wp-block-list">%s</%s>\n<!-- /wp:list -->' % (_attrs(attrs), tag, inner, tag)


def _quote(text, cite=None):
    cite_html = "<cite>%s</cite>" % _inline(cite) if cite else ""
    return '<!-- wp:quote -->\n<blockquote class="wp-block-quote">%s%s</blockquote>\n<!-- /wp:quote -->' % (_paragraph(text), cite_html)


def _group(inner_blocks, class_name):
    attrs = {"className": class_name, "layout": {"type": "constrained"}}
    return '<!-- wp:group%s -->\n<div class="wp-block-group %s">%s</div>\n<!-- /wp:group -->' % (
        _attrs(attrs),
        class_name,
        "\n\n".join(inner_blocks),
    )


def _table(head, rows, class_name):
    attrs = {"hasFixedLayout": True, "className": class_name, "fontSize": "small"}
    head_html = "".join("<th>%s</th>" % _inline(cell) for cell in head)
    body_html = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(cell) for cell in row) for row in rows)
    return (
        '<!-- wp:table%s -->\n<figure class="wp-block-table %s has-small-font-size"><table class="has-fixed-layout">'
        "<thead><tr>%s</tr></thead><tbody>%s</tbody></table></figure>\n<!-- /wp:table -->"
    ) % (_attrs(attrs), class_name, head_html, body_html)


def _image(spec):
    attrs = {"id": spec["id"], "sizeSlug": "large", "linkDestination": "none"}
    figure = '<figure class="wp-block-image size-large"><img src="%s" alt="%s" class="wp-image-%d"/>' % (
        _esc(spec["src"]),
        _esc(spec.get("alt")),
        int(spec["id"]),
    )
    if spec.get("caption"):
        figure += '<figcaption class="wp-element-caption">%s</figcaption>' % _inline(spec["caption"])
    figure += "</figure>"
    return "<!-- wp:image%s -->\n%s\n<!-- /wp:image -->" % (_attrs(attrs), figure)


def _embed(url):
    attrs = {
        "url": url,
        "type": "video",
        "providerNameSlug": "youtube",
        "responsive": True,
        "className": "wp-embed-aspect-16-9 wp-has-aspect-ratio",
    }
    return (
        "<!-- wp:embed%s -->\n"
        '<figure class="wp-block-embed is-type-video is-provider-youtube wp-block-embed-youtube wp-embed-aspect-16-9 wp-has-aspect-ratio">'
        '<div class="wp-block-embed__wrapper">\n%s\n</div></figure>\n<!-- /wp:embed -->'
    ) % (_attrs(attrs), _esc(url))


def render_content(draft, media):
    article = draft["article"]
    kind = draft.get("kind", "text")
    blocks = []
    if article.get("subtitle"):
        blocks.append(_paragraph(article["subtitle"], class_name="pipSubtitle", italic=True))

    summary_inner = [_heading(SUMMARY_HEADINGS.get(kind, "Ringkasan"), 2)]
    if article["summary"]["text"]:
        summary_inner.append(_paragraph(article["summary"]["text"]))
    if article["summary"]["points"]:
        summary_inner.append(_list(article["summary"]["points"]))
    blocks.append(_group(summary_inner, "pipSummary"))

    video_url = (draft.get("source") or {}).get("url")
    if kind == "video" and video_url:
        blocks.append(_embed(video_url))

    for section in article["sections"]:
        if section.get("heading"):
            blocks.append(_heading(section["heading"], 2))
        image = media.get(section.get("image") or "")
        body = []
        for block in section["blocks"]:
            if block["type"] == "list":
                body.append(_list(block["items"]))
            elif block["type"] == "steps":
                body.append(_list(block["items"], ordered=True))
            elif block["type"] == "quote":
                body.append(_quote(block["text"], block.get("by")))
            elif block["type"] == "callout":
                body.append(_paragraph(block["text"], class_name="pipCallout"))
            else:
                body.append(_paragraph(block["text"]))
        if image:
            position = 1 if body and body[0].startswith("<!-- wp:paragraph") else 0
            body.insert(position, _image(image))
        blocks.extend(body)

    blocks.append(_heading(article["conclusion"]["heading"], 2))
    for para in article["conclusion"]["paragraphs"]:
        blocks.append(_paragraph(para))

    if article.get("cta"):
        blocks.append(_group([_paragraph("**%s**" % article["cta"])], "pipCta"))

    if article["glossary"]:
        blocks.append(_heading("Glosarium", 2))
        blocks.append(_table(["Istilah", "Arti"], [[g["term"], g["definition"]] for g in article["glossary"]], "pipGlossary"))

    return "\n\n".join(blocks)


def word_count(content):
    return len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", content)))


def clean_slug(value):
    value = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    if len(value) < 4:
        value = "artikel"
    return value[:70].strip("-")


def slug_for(draft):
    article = draft["article"]
    return clean_slug(article.get("slug") or article.get("title"))


def media_filename(draft, image, position):
    return "%s_%02d.jpg" % (slug_for(draft)[:50], position + 1)


def _nicename(value):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(value or "").lower())).strip("-") or "tanpa-nama"


def _metadata(width, height, attached_file, alt):
    return (
        'a:5:{s:5:"width";i:%d;s:6:"height";i:%d;s:4:"file";s:%d:"%s";s:5:"sizes";a:0:{}s:10:"image_meta";a:0:{}}'
        % (int(width or 0), int(height or 0), len(attached_file.encode("utf-8")), attached_file)
    )


def ordered_images(draft):
    article = draft["article"]
    wanted = [s["image"] for s in article["sections"] if s.get("image")]
    by_key = {img["key"]: img for img in draft["images"]}
    result = []
    featured = next((img for img in draft["images"] if img.get("role") == "featured"), None)
    if featured:
        result.append(featured)
    for key in wanted:
        img = by_key.get(key)
        if img and img not in result:
            result.append(img)
    return result


def build_package(draft, out_dir, public_base=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    article = draft["article"]
    public_base = (public_base if public_base is not None else config.PUBLIC_BASE_URL).rstrip("/")
    slug = slug_for(draft)
    date_path = dt.datetime.now().strftime("%Y/%m")
    site = config.SITE_LINK.rstrip("/")
    post_id = 1

    images = ordered_images(draft)
    media = {}
    attachments = []
    for position, img in enumerate(images):
        filename = media_filename(draft, img, position)
        attached = "%s/%s" % (date_path, filename)
        url = "%s/files/%s" % (public_base, filename) if public_base else "%s/wp-content/uploads/%s" % (site, attached)
        content_src = url if public_base else "/wp-content/uploads/%s" % attached
        attachment_id = 10001 + position
        attachments.append({"id": attachment_id, "img": img, "filename": filename, "attached": attached, "url": url})
        media[img["key"]] = {"id": attachment_id, "src": content_src, "alt": img.get("alt"), "caption": img.get("caption")}

    content = render_content(draft, media)
    words = word_count(content)
    now = _now()
    thumb = next((a for a in attachments if a["img"].get("role") == "featured"), None)

    lines = ['<?xml version="1.0" encoding="UTF-8" ?>']
    lines.append(
        '<rss version="2.0"\n\txmlns:excerpt="http://wordpress.org/export/1.2/excerpt/"\n\txmlns:content="http://purl.org/rss/1.0/modules/content/"'
        '\n\txmlns:wfw="http://wellformedweb.org/CommentAPI/"\n\txmlns:dc="http://purl.org/dc/elements/1.1/"\n\txmlns:wp="http://wordpress.org/export/1.2/">'
    )
    lines.append("<channel>")
    lines.append("\t<title>%s</title>" % _esc(config.SITE_TITLE))
    lines.append("\t<link>%s</link>" % _esc(site))
    lines.append("\t<description>Artikel dari bot Telegram</description>")
    lines.append("\t<pubDate>%s</pubDate>" % _iso(now))
    lines.append("\t<language>%s</language>" % _esc(config.SITE_LANGUAGE))
    lines.append("\t<wp:wxr_version>1.2</wp:wxr_version>")
    lines.append("\t<wp:base_site_url>%s</wp:base_site_url>" % _esc(site))
    lines.append("\t<wp:base_blog_url>%s</wp:base_blog_url>" % _esc(site))
    lines.append(
        "\t<wp:author><wp:author_id>1</wp:author_id><wp:author_login>%s</wp:author_login>"
        "<wp:author_email>%s</wp:author_email><wp:author_display_name>%s</wp:author_display_name>"
        "<wp:author_first_name></wp:author_first_name><wp:author_last_name></wp:author_last_name></wp:author>"
        % (_cd(config.WP_AUTHOR_LOGIN), _cd(config.WP_AUTHOR_EMAIL), _cd(config.WP_AUTHOR_LOGIN))
    )
    lines.append(
        "\t<wp:category><wp:term_id>1</wp:term_id><wp:category_nicename>%s</wp:category_nicename>"
        "<wp:category_parent></wp:category_parent><wp:cat_name>%s</wp:cat_name></wp:category>"
        % (_cd(_nicename(article["category"])), _cd(article["category"]))
    )
    for index, name in enumerate(article["tags"]):
        lines.append(
            "\t<wp:tag><wp:term_id>%d</wp:term_id><wp:tag_slug>%s</wp:tag_slug><wp:tag_name>%s</wp:tag_name></wp:tag>"
            % (index + 2, _cd(_nicename(name)), _cd(name))
        )

    meta = [
        ("_yoast_wpseo_metadesc", article.get("excerpt")),
        ("_yoast_wpseo_focuskw", article.get("focus_keyword")),
        ("_yoast_wpseo_title", "%s %%%%sep%%%% %%%%sitename%%%%" % article["seo_title"] if article.get("seo_title") else ""),
        ("pip_subtitle", article.get("subtitle")),
        ("pip_title_tone", article.get("tone")),
    ]
    if draft.get("kind") == "video":
        meta.append(("pip_video_url", (draft.get("source") or {}).get("url")))
    if thumb:
        meta.append(("_thumbnail_id", str(thumb["id"])))

    lines.append("\t<item>")
    lines.append("\t\t<title>%s</title>" % _cd(article["title"]))
    lines.append("\t\t<link>%s/%s/</link>" % (_esc(site), _esc(slug)))
    lines.append("\t\t<pubDate>%s</pubDate>" % _iso(now))
    lines.append("\t\t<dc:creator>%s</dc:creator>" % _cd(config.WP_AUTHOR_LOGIN))
    lines.append('\t\t<guid isPermaLink="false">%s/?p=%d</guid>' % (_esc(site), post_id))
    lines.append("\t\t<description></description>")
    lines.append("\t\t<content:encoded>%s</content:encoded>" % _cd(content))
    lines.append("\t\t<excerpt:encoded>%s</excerpt:encoded>" % _cd(article.get("excerpt")))
    lines.append("\t\t<wp:post_id>%d</wp:post_id>" % post_id)
    lines.append("\t\t<wp:post_date>%s</wp:post_date>" % _cd(now))
    lines.append("\t\t<wp:post_date_gmt>%s</wp:post_date_gmt>" % _cd(now))
    lines.append("\t\t<wp:comment_status>closed</wp:comment_status>")
    lines.append("\t\t<wp:ping_status>closed</wp:ping_status>")
    lines.append("\t\t<wp:post_name>%s</wp:post_name>" % _cd(slug))
    lines.append("\t\t<wp:status>draft</wp:status>")
    lines.append("\t\t<wp:post_parent>0</wp:post_parent>")
    lines.append("\t\t<wp:menu_order>0</wp:menu_order>")
    lines.append("\t\t<wp:post_type>post</wp:post_type>")
    lines.append("\t\t<wp:post_password></wp:post_password>")
    lines.append("\t\t<wp:is_sticky>0</wp:is_sticky>")
    lines.append('\t\t<category domain="category" nicename="%s">%s</category>' % (_esc(_nicename(article["category"])), _cd(article["category"])))
    for name in article["tags"]:
        lines.append('\t\t<category domain="post_tag" nicename="%s">%s</category>' % (_esc(_nicename(name)), _cd(name)))
    for key, value in meta:
        if value:
            lines.append("\t\t<wp:postmeta><wp:meta_key>%s</wp:meta_key><wp:meta_value>%s</wp:meta_value></wp:postmeta>" % (_cd(key), _cd(value)))
    lines.append("\t</item>")

    for item in attachments:
        img = item["img"]
        lines.append("\t<item>")
        lines.append("\t\t<title>%s</title>" % _cd((img.get("caption") or img.get("alt") or article["title"])[:180]))
        lines.append("\t\t<link>%s</link>" % _esc(item["url"]))
        lines.append("\t\t<pubDate>%s</pubDate>" % _iso(now))
        lines.append("\t\t<dc:creator>%s</dc:creator>" % _cd(config.WP_AUTHOR_LOGIN))
        lines.append('\t\t<guid isPermaLink="false">%s</guid>' % _esc(item["url"]))
        lines.append("\t\t<description></description>")
        lines.append("\t\t<content:encoded></content:encoded>")
        lines.append("\t\t<excerpt:encoded>%s</excerpt:encoded>" % _cd(img.get("caption")))
        lines.append("\t\t<wp:post_id>%d</wp:post_id>" % item["id"])
        lines.append("\t\t<wp:post_date>%s</wp:post_date>" % _cd(now))
        lines.append("\t\t<wp:post_date_gmt>%s</wp:post_date_gmt>" % _cd(now))
        lines.append("\t\t<wp:comment_status>closed</wp:comment_status>")
        lines.append("\t\t<wp:ping_status>closed</wp:ping_status>")
        lines.append("\t\t<wp:post_name>%s</wp:post_name>" % _cd(_nicename(item["filename"])))
        lines.append("\t\t<wp:status>inherit</wp:status>")
        lines.append("\t\t<wp:post_parent>%d</wp:post_parent>" % post_id)
        lines.append("\t\t<wp:menu_order>0</wp:menu_order>")
        lines.append("\t\t<wp:post_type>attachment</wp:post_type>")
        lines.append("\t\t<wp:post_password></wp:post_password>")
        lines.append("\t\t<wp:is_sticky>0</wp:is_sticky>")
        lines.append("\t\t<wp:attachment_url>%s</wp:attachment_url>" % _cd(item["url"]))
        lines.append("\t\t<wp:postmeta><wp:meta_key>_wp_attached_file</wp:meta_key><wp:meta_value>%s</wp:meta_value></wp:postmeta>" % _cd(item["attached"]))
        lines.append("\t\t<wp:postmeta><wp:meta_key>_wp_attachment_image_alt</wp:meta_key><wp:meta_value>%s</wp:meta_value></wp:postmeta>" % _cd(img.get("alt")))
        lines.append(
            "\t\t<wp:postmeta><wp:meta_key>_wp_attachment_metadata</wp:meta_key><wp:meta_value>%s</wp:meta_value></wp:postmeta>"
            % _cd(_metadata(img.get("width"), img.get("height"), item["attached"], img.get("alt")))
        )
        lines.append("\t</item>")

    lines.append("</channel>")
    lines.append("</rss>")

    xml_path = out_dir / ("%s.xml" % slug)
    xml_path.write_text("\n".join(lines), encoding="utf-8")

    zip_path = None
    local = [a for a in attachments if a["img"].get("path") and Path(a["img"]["path"]).exists()]
    if local:
        zip_path = out_dir / ("%s_artikel.zip" % slug)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(xml_path, xml_path.name)
            for item in local:
                archive.write(item["img"]["path"], "wp-content/uploads/%s" % item["attached"])
            archive.writestr(
                "BACA_SAYA.txt",
                "CARA PAKAI TANPA URL PUBLIK\n"
                "1. Salin folder wp-content di zip ini ke document root WordPress.\n"
                "2. Buka Tools, Import, WordPress, lalu upload %s.\n"
                "3. Jangan centang Download and import file attachments karena file sudah ada di server.\n"
                "4. Pilih author lalu submit.\n\n"
                "Kalau bot punya URL publik, cukup upload file xml dan centang download attachments.\n" % xml_path.name,
            )

    return {
        "xml_path": str(xml_path),
        "zip_path": str(zip_path) if zip_path else None,
        "slug": slug,
        "words": words,
        "images": len(attachments),
        "public_urls": bool(public_base),
    }
