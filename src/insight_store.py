# -*- coding: utf-8 -*-
"""
insight_store.py — LLM 인사이트 보관함 + PPT 보고서 생성.

보관함:
- LLM 이 생성한 인사이트(버튼 결과·챗 답변)를 storage("insights")에 자동 저장한다
  (Dataiku 프로젝트 변수 / 로컬 JSON — Backend 재시작 후에도 유지, 최근 300건).
- 항목: {id, kind(report|chat), analysis, title, question?, sentences[], dataset,
        created_at}

PPT 보고서:
- 저장된 인사이트를 .pptx 로 내보낸다. python-pptx 가 설치되어 있으면 사용하고,
  없으면 외부 의존성 없는 내장 OOXML 생성기(_minimal_pptx)로 생성한다 —
  표지 1장 + 인사이트당 1장(길면 이어짐 슬라이드), 텍스트 전용 16:9.
"""
import base64
import io
import logging
import os
import re
import time
import uuid
import zipfile
from xml.sax.saxutils import escape

from src import storage

logger = logging.getLogger("ip_landscape")

_MAX_ITEMS = 300
_LINES_PER_SLIDE = 13
_MAX_IMAGE_MB = 4
_DATAURL_RE = re.compile(r"^data:image/(png|jpeg);base64,(.+)$", re.DOTALL)


def _save_chart_image(insight_id, chart_image):
    """프론트가 보낸 차트 캡처(data URL) → PNG/JPEG 파일 저장. 파일명 또는 None."""
    m = _DATAURL_RE.match(str(chart_image or "").strip())
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except Exception:
        return None
    if not raw or len(raw) > _MAX_IMAGE_MB * 1024 * 1024:
        return None
    fname = "%s.%s" % (insight_id, "png" if m.group(1) == "png" else "jpg")
    try:
        with open(os.path.join(storage.insight_image_dir(), fname), "wb") as fh:
            fh.write(raw)
        return fname
    except OSError as e:
        logger.warning("인사이트 이미지 저장 실패: %s", e)
        return None


def _image_path(entry):
    fname = entry.get("image_file")
    if not fname:
        return None
    path = os.path.join(storage.insight_image_dir(), str(fname))
    return path if os.path.exists(path) else None


def _remove_image(entry):
    path = _image_path(entry)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def add_insight(analysis, title, sentences, dataset=None, kind="report",
                question=None, chart_image=None):
    """LLM 인사이트 저장 (+차트 캡처 이미지 — PPT 삽입용). 반환: 항목 id."""
    sentences = [str(s).strip() for s in (sentences or []) if str(s).strip()][:40]
    if not sentences:
        return None
    uid = uuid.uuid4().hex[:10]
    entry = {
        "id": uid, "kind": kind,
        "analysis": str(analysis or "")[:60],
        "title": str(title or analysis or "인사이트")[:160],
        "question": (str(question)[:200] if question else None),
        "sentences": sentences,
        "dataset": (str(dataset)[:80] if dataset else None),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "image_file": _save_chart_image(uid, chart_image),
    }
    data = storage.load_store("insights")
    items = list(data.get("items") or [])
    items.insert(0, entry)
    for evicted in items[_MAX_ITEMS:]:  # 상한 초과분의 이미지 파일 정리
        _remove_image(evicted)
    storage.save_store("insights", {"items": items[:_MAX_ITEMS]})
    return entry["id"]


def list_insights():
    items = list(storage.load_store("insights").get("items") or [])
    for it in items:
        it["has_image"] = _image_path(it) is not None
    return items


def get_image(insight_id):
    """항목의 차트 이미지 (bytes, mimetype) 또는 (None, None)."""
    for it in storage.load_store("insights").get("items") or []:
        if str(it.get("id")) == str(insight_id):
            path = _image_path(it)
            if path:
                with open(path, "rb") as fh:
                    return fh.read(), ("image/png" if path.endswith(".png")
                                       else "image/jpeg")
    return None, None


def delete_insight(insight_id):
    data = storage.load_store("insights")
    items = list(data.get("items") or [])
    for it in items:
        if str(it.get("id")) == str(insight_id):
            _remove_image(it)
    items = [it for it in items if str(it.get("id")) != str(insight_id)]
    storage.save_store("insights", {"items": items})
    return True


def get_insights(ids=None):
    items = list_insights()
    if not ids:
        return items
    wanted = set(map(str, ids))
    return [it for it in items if str(it.get("id")) in wanted]


# ---------------------------------------------------------------------------
# PPTX 생성
# ---------------------------------------------------------------------------
def build_pptx(items, report_title="IP Landscape 인사이트 보고서"):
    """인사이트 목록 → .pptx 바이트. python-pptx 우선, 내장 생성기 폴백."""
    slides = _to_slides(items, report_title)
    try:
        return _pptx_via_library(slides)
    except ImportError:
        return _minimal_pptx(slides)


def _to_slides(items, report_title):
    """항목 → [{"title","lines","image","ext"}]. 긴 항목은 이어짐 슬라이드로 분할.

    차트 캡처 이미지가 있으면 첫 슬라이드에 차트(좌) + 인사이트(우)로 배치된다.
    """
    slides = [{"title": report_title, "image": None, "ext": None,
               "lines": ["생성일: %s" % time.strftime("%Y-%m-%d"),
                         "포함 인사이트: %d건" % len(items),
                         "", "본 보고서의 지표는 특허 데이터 기반 통계 신호이며 "
                         "법률 자문(FTO·유효성 판단)을 대체하지 않습니다."]}]
    for it in items:
        title = str(it.get("title") or it.get("analysis") or "인사이트")
        # 첫 줄이 [슬라이드 제목] 헤드라인이면 그 내용을 슬라이드 제목으로 사용
        lines = list(it.get("sentences") or [])
        if lines and lines[0].startswith("[슬라이드 제목]"):
            title = lines[0].replace("[슬라이드 제목]", "").strip() or title
            lines = lines[1:]
        meta_line = "· %s · %s%s" % (it.get("analysis", ""),
                                     it.get("created_at", ""),
                                     (" · Q: %s" % it["question"])
                                     if it.get("question") else "")
        lines = [meta_line] + lines
        image = None
        ext = None
        path = _image_path(it)
        if path:
            try:
                with open(path, "rb") as fh:
                    image = fh.read()
                ext = "png" if path.endswith(".png") else "jpg"
            except OSError:
                image = None
        for start in range(0, len(lines), _LINES_PER_SLIDE):
            chunk = lines[start:start + _LINES_PER_SLIDE]
            t = title if start == 0 else title[:60] + " (계속)"
            slides.append({"title": t[:120], "lines": chunk,
                           "image": image if start == 0 else None,
                           "ext": ext if start == 0 else None})
    return slides


def _pptx_via_library(slides):
    from pptx import Presentation  # noqa — 미설치 시 ImportError → 내장 생성기
    from pptx.util import Inches, Pt
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for sl in slides:
        slide = prs.slides.add_slide(blank)
        tbox = slide.shapes.add_textbox(Inches(0.5), Inches(0.35),
                                        Inches(12.3), Inches(1.0))
        p = tbox.text_frame.paragraphs[0]
        p.text = sl["title"]
        p.font.size = Pt(24)
        p.font.bold = True
        has_img = bool(sl.get("image"))
        if has_img:
            slide.shapes.add_picture(io.BytesIO(sl["image"]),
                                     Inches(0.4), Inches(1.45),
                                     width=Inches(7.1), height=Inches(4.14))
            body_x, body_w, fsize = Inches(7.7), Inches(5.2), 11
        else:
            body_x, body_w, fsize = Inches(0.6), Inches(12.1), 14
        body = slide.shapes.add_textbox(body_x, Inches(1.5), body_w, Inches(5.6))
        tf = body.text_frame
        tf.word_wrap = True
        for i, line in enumerate(sl["lines"]):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = str(line)
            para.font.size = Pt((fsize + 4) if line.startswith("[") else fsize)
            para.font.bold = line.startswith("[")
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---- 내장 OOXML 생성기 (외부 의존성 없음, 텍스트 전용 16:9) ----------------
_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
%s</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')

_THEME = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="T">
<a:themeElements><a:clrScheme name="C"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1F3B54"/></a:dk2>
<a:lt2><a:srgbClr val="EEF2F6"/></a:lt2><a:accent1><a:srgbClr val="4E79A7"/></a:accent1>
<a:accent2><a:srgbClr val="F28E2B"/></a:accent2><a:accent3><a:srgbClr val="59A14F"/></a:accent3>
<a:accent4><a:srgbClr val="E15759"/></a:accent4><a:accent5><a:srgbClr val="76B7B2"/></a:accent5>
<a:accent6><a:srgbClr val="EDC948"/></a:accent6><a:hlink><a:srgbClr val="1668A8"/></a:hlink>
<a:folHlink><a:srgbClr val="800080"/></a:folHlink></a:clrScheme>
<a:fontScheme name="F"><a:majorFont><a:latin typeface="Malgun Gothic"/><a:ea typeface="Malgun Gothic"/><a:cs typeface=""/></a:majorFont>
<a:minorFont><a:latin typeface="Malgun Gothic"/><a:ea typeface="Malgun Gothic"/><a:cs typeface=""/></a:minorFont></a:fontScheme>
<a:fmtScheme name="S"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>
<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>
</a:fmtScheme></a:themeElements></a:theme>"""

_MASTER = ("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster %s><p:cSld><p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr/></p:spTree></p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>""" % _NS)

_MASTER_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

_LAYOUT = ("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout %s type="blank"><p:cSld><p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr/></p:spTree></p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>""" % _NS)

_LAYOUT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

_SLIDE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
%s</Relationships>"""

_IMG_REL = ('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/image" Target="../media/%s"/>')


def _picture_xml(shape_id, x, y, w, h):
    """차트 캡처 이미지 pic 요소 (r:embed=rId2)."""
    return ('<p:pic><p:nvPicPr><p:cNvPr id="%d" name="chart"/>'
            '<p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
            '<p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/>'
            '</a:stretch></p:blipFill>'
            '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
            % (shape_id, x, y, w, h))


def _textbox(shape_id, name, x, y, w, h, paragraphs):
    """EMU 좌표 텍스트박스 sp XML. paragraphs: [(text, size_pt, bold)]"""
    paras = []
    for text, size, bold in paragraphs:
        t = escape(str(text)) or " "
        paras.append(
            '<a:p><a:pPr/><a:r><a:rPr lang="ko-KR" sz="%d" b="%d" dirty="0"/>'
            '<a:t>%s</a:t></a:r></a:p>' % (int(size * 100), 1 if bold else 0, t))
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/>'
            '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            '<p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr>'
            '<a:lstStyle/>%s</p:txBody></p:sp>'
            % (shape_id, name, x, y, w, h, "".join(paras)))


def _slide_xml(title, lines, has_image=False):
    title_box = _textbox(2, "title", 457200, 320040, 11277600, 914400,
                         [(title, 24, True)])
    body_paras = []
    base_size = 11 if has_image else 14
    for line in lines:
        is_head = str(line).startswith("[")
        body_paras.append((line, (base_size + 4) if is_head else base_size, is_head))
    if has_image:
        # 차트(좌 7.1") + 인사이트 텍스트(우 5.2")
        pic = _picture_xml(4, 365760, 1326000, 6492240, 3786000)
        body_box = _textbox(3, "body", 7040880, 1326000, 4754880, 5120640,
                            body_paras or [(" ", base_size, False)])
        shapes = pic + body_box
    else:
        body_box = _textbox(3, "body", 548640, 1371600, 11094720, 5120640,
                            body_paras or [(" ", base_size, False)])
        shapes = body_box
    return ("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld %s><p:cSld><p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr/>%s%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"""
            % (_NS, title_box, shapes))


def _minimal_pptx(slides):
    """외부 의존성 없는 PPTX 생성 (16:9, 텍스트 전용)."""
    n = len(slides)
    ct_overrides = "".join(
        '<Override PartName="/ppt/slides/slide%d.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        % (i + 1) for i in range(n))
    pres_rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
                 'officeDocument/2006/relationships/slideMaster" '
                 'Target="slideMasters/slideMaster1.xml"/>']
    sld_ids = []
    for i in range(n):
        rid = "rId%d" % (i + 2)
        pres_rels.append('<Relationship Id="%s" Type="http://schemas.openxmlformats.'
                         'org/officeDocument/2006/relationships/slide" '
                         'Target="slides/slide%d.xml"/>' % (rid, i + 1))
        sld_ids.append('<p:sldId id="%d" r:id="%s"/>' % (256 + i, rid))
    presentation = ("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation %s><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
<p:sldIdLst>%s</p:sldIdLst>
<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>""" % (_NS, "".join(sld_ids)))
    pres_rels_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/'
                     'package/2006/relationships">%s</Relationships>'
                     % "".join(pres_rels))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT % ct_overrides)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("ppt/presentation.xml", presentation)
        z.writestr("ppt/_rels/presentation.xml.rels", pres_rels_xml)
        z.writestr("ppt/slideMasters/slideMaster1.xml", _MASTER)
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _MASTER_RELS)
        z.writestr("ppt/slideLayouts/slideLayout1.xml", _LAYOUT)
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _LAYOUT_RELS)
        z.writestr("ppt/theme/theme1.xml", _THEME)
        for i, sl in enumerate(slides):
            has_img = bool(sl.get("image"))
            img_rel = ""
            if has_img:
                media_name = "image%d.%s" % (i + 1, sl.get("ext") or "png")
                z.writestr("ppt/media/%s" % media_name, sl["image"])
                img_rel = _IMG_REL % media_name
            z.writestr("ppt/slides/slide%d.xml" % (i + 1),
                       _slide_xml(sl["title"], sl["lines"], has_image=has_img))
            z.writestr("ppt/slides/_rels/slide%d.xml.rels" % (i + 1),
                       _SLIDE_RELS % img_rel)
    return buf.getvalue()
