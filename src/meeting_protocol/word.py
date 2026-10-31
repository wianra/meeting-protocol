"""Small, deterministic Word export with no services or additional runtime dependencies."""

import io
import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def text_xml(value):
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", value):
        raise ValueError("The transcript contains a control character unsupported by Word.")
    return escape(value)


def word_document(turns):
    """A4, readable body text, bold speaker names, and no timestamps or added content.

    `turns` contains already normalised (speaker, text) pairs, shared with plain text.
    Long turns may span pages; widow control prevents isolated paragraph lines.
    """
    paragraphs = []
    for speaker, text in turns:
        paragraphs.append(
            '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">'
            + text_xml(speaker + ": ")
            + '</w:t></w:r><w:r><w:t xml:space="preserve">'
            + text_xml(text)
            + "</w:t></w:r></w:p>"
        )
    parts = {
        "[Content_Types].xml": XML
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>",
        "_rels/.rels": XML
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>",
        "word/_rels/document.xml.rels": XML
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>",
        "word/styles.xml": XML + f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
        '<w:color w:val="000000"/><w:sz w:val="22"/><w:szCs w:val="22"/>'
        "</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:widowControl/>"
        '<w:spacing w:after="160" w:line="276" w:lineRule="auto"/>'
        "</w:pPr></w:pPrDefault></w:docDefaults>"
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/></w:style></w:styles>',
        "word/document.xml": XML
        + f'<w:document xmlns:w="{W}"><w:body>'
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1247" w:right="1247" w:bottom="1247" w:left="1247" '
        'w:header="0" w:footer="0" w:gutter="0"/></w:sectPr></w:body></w:document>',
    }
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, data in parts.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data.encode("utf-8"))
    return buffer.getvalue()
