import csv
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from charset_normalizer import from_bytes
from docx import Document as WordDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openpyxl import load_workbook
from PIL import Image
import xlrd

from . import db
from .models import understand_image

SUPPORTED = {'docx', 'pdf', 'md', 'txt', 'png', 'jpg', 'jpeg', 'webp', 'xlsx', 'xls', 'csv'}


def normalize_split_options(options):
    if not isinstance(options, dict):
        raise ValueError('切分参数必须为对象')
    mode = options.get('mode', 'structure')
    mode = 'structure' if mode == 'smart' else mode
    if mode not in ('structure', 'length', 'paragraph', 'separator'):
        raise ValueError('请选择有效的切分方式')
    numbers = []
    for key, default in (('chunkSize', 800), ('overlap', 100)):
        value = options.get(key, default)
        if type(value) is int:
            numbers.append(value)
        elif isinstance(value, str) and re.fullmatch(r'[+-]?\d{1,8}', value.strip()):
            numbers.append(int(value.strip()))
        else:
            raise ValueError('分段长度和重叠长度须为整数')
    chunk_size, overlap = numbers
    if not 200 <= chunk_size <= 4000 or not 0 <= overlap < chunk_size:
        raise ValueError('分段长度须为200–4000，重叠长度须大于等于0且小于分段长度')
    result = {'mode': mode, 'chunkSize': chunk_size, 'overlap': overlap}
    if mode == 'separator':
        separator = options.get('separator', '\\n\\n')
        if not isinstance(separator, str) or not separator or len(separator) > 100:
            raise ValueError('请输入1–100字符的自定义分隔符')
        result['separator'] = separator
    return result


def _chunk_identity(chunk):
    return json.dumps({key: value for key, value in chunk.items() if key != 'id' and value is not None}, sort_keys=True, ensure_ascii=False)


def split_blocks(blocks, options, document_id='', existing=()):
    """Use the same local splitter for parsing, live preview and final publication."""
    options = normalize_split_options(options)
    splitter = RecursiveCharacterTextSplitter(chunk_size=options['chunkSize'], chunk_overlap=options['overlap'], separators=[''] if options['mode'] == 'length' else ['\n\n', '\n', '。', '；', ' ', ''])
    previous_ids = {_chunk_identity(chunk): chunk['id'] for chunk in existing}
    result, seen = [], set()
    for block in blocks:
        metadata = {key: value for key, value in block.items() if key not in ('id', 'text') and value is not None}
        text = block['text']
        if metadata['kind'] in ('table', 'image'):
            parts = [text]
        else:
            if options['mode'] == 'paragraph':
                sections = re.split(r'\n[ \t]*\n+', text)
            elif options['mode'] == 'separator':
                separator = options['separator'].replace('\\r', '\r').replace('\\n', '\n').replace('\\t', '\t')
                sections = text.split(separator)
            else:
                sections = [text]
            parts = [part for section in sections if section.strip() for part in splitter.split_text(section)]
        for text in parts:
            identity = (text, metadata.get('page'), metadata.get('sheet'), metadata['kind'])
            if identity in seen:
                continue
            seen.add(identity)
            chunk = {'text': text, **metadata}
            identity_key = _chunk_identity(chunk)
            chunk['id'] = previous_ids.get(identity_key) or uuid.uuid5(uuid.NAMESPACE_URL, document_id + ':' + identity_key).hex
            result.append(chunk)
    if not result:
        raise ValueError('没有提取到可用内容；若为扫描文档，请配置 OCR 后重试')
    return result


def source_blocks(doc):
    """Keep OCR results local; previews must never rerun OCR or other cloud calls."""
    if doc.get('sourceBlocks'):
        return doc['sourceBlocks']
    blocks = []
    overlap = max(0, min(4000, int((doc.get('parseOptions') or {}).get('overlap', 100))))
    for chunk in doc.get('chunks') or []:
        block = {key: value for key, value in chunk.items() if key != 'id'}
        same_source = bool(blocks and block.get('kind') == 'text' and {key: value for key, value in blocks[-1].items() if key != 'text'} == {key: value for key, value in block.items() if key != 'text'})
        if same_source:
            previous, current = blocks[-1]['text'], block['text']
            shared = next((size for size in range(min(overlap, len(previous), len(current)), 0, -1) if previous.endswith(current[:size])), 0)
            blocks[-1]['text'] += current[shared:] if shared else '\n\n' + current
        else:
            blocks.append(block)
    return blocks


def resplit_document(doc, options):
    options = normalize_split_options(options)
    if options == normalize_split_options(doc.get('parseOptions') or {}):
        return doc['chunks']
    return split_blocks(source_blocks(doc), options, doc['id'], doc.get('chunks') or [])


def decode(raw):
    match = from_bytes(raw).best()
    if match is None:
        raise ValueError('文本编码无法识别，请另存为 UTF-8 后重试')
    return str(match)


def table_markdown(rows):
    rows = [[str(value if value is not None else '').replace('|', '\\|').replace('\n', '<br>') for value in row] for row in rows]
    rows = [row for row in rows if any(value.strip() for value in row)]
    if not rows:
        return ''
    columns = max(len(row) for row in rows)
    normalized = [row + [''] * (columns - len(row)) for row in rows]
    return '\n'.join(['| ' + ' | '.join(normalized[0]) + ' |', '| ' + ' | '.join(['---'] * columns) + ' |'] + ['| ' + ' | '.join(row) + ' |' for row in normalized[1:]])


def asset(doc, raw, name):
    folder = db.DATA / 'assets' / doc['id']
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(name).name
    target.write_bytes(raw)
    return f'/api/documents/{doc["id"]}/assets/{target.name}'


def zip_guard(path):
    if not zipfile.is_zipfile(path):
        raise ValueError('文件结构无效，无法读取 Office 文档')
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 200 * 1024 * 1024:
            raise ValueError('Office 文件解压后超过 200 MB，请拆分后上传')


def parse_document(doc, options, progress=lambda *_: None, warnings=None, extracted_blocks=None):
    options = {**options, **normalize_split_options(options)}
    path = db.DATA / doc['storagePath']
    kind = doc['type'].lower()
    blocks = []
    pages = 0
    warnings = warnings if warnings is not None else []
    def warn(message):
        if message not in warnings:
            warnings.append(message)
    def add(title, text, block_kind='text', **metadata):
        if text and text.strip():
            blocks.append(Document(page_content=text.strip(), metadata={'title': title, 'kind': block_kind, **metadata}))
    def picture(raw, title, name, page=None):
        uri = asset(doc, raw, name)
        processed = False
        if options.get('ocr'):
            add(title + ' · 识别文字', understand_image(raw, 'OCR', doc['kbId']), 'text', imageUrl=uri, page=page, extraction='ocr')
            processed = True
        if options.get('vision'):
            add(title + ' · 图片理解', understand_image(raw, 'Vision', doc['kbId']), 'image', imageUrl=uri, page=page, extraction='vision')
            processed = True
        return processed

    if kind in ('md', 'txt'):
        text = decode(path.read_bytes())
        title = doc['name']
        paragraph = []
        for line in text.splitlines():
            if re.match(r'^#{1,6}\s+', line):
                add(title, '\n'.join(paragraph)); paragraph = []
                title = re.sub(r'^#+\s+', '', line)
            paragraph.append(line)
        add(title, '\n'.join(paragraph))
    elif kind == 'docx':
        zip_guard(path)
        word = WordDocument(path)
        title, paragraphs = doc['name'], []
        for child in word.element.body.iterchildren():
            if child.tag.endswith('}p'):
                paragraph = Paragraph(child, word)
                if paragraph.style and paragraph.style.name.startswith(('Heading', '标题')):
                    add(title, '\n\n'.join(paragraphs)); paragraphs = []; title = paragraph.text or title
                paragraphs.append(paragraph.text)
            elif child.tag.endswith('}tbl'):
                add(title, '\n\n'.join(paragraphs)); paragraphs = []
                table = Table(child, word)
                add(title + ' · 表格', table_markdown([[cell.text for cell in row.cells] for row in table.rows]), 'table')
        add(title, '\n\n'.join(paragraphs))
        image_relations = [rel for rel in word.part.rels.values() if 'image' in rel.reltype]
        images = [rel.target_part for rel in image_relations if not rel.is_external]
        linked_images = sum(rel.is_external for rel in image_relations)
        if linked_images:
            warn(f'Word 包含 {linked_images} 张外部链接图片，本次未下载链接内容；请将图片嵌入文档或单独上传后处理。')
        if images and not (options.get('ocr') or options.get('vision')):
            warn(f'Word 包含 {len(images)} 张内嵌图片，未开启 OCR 或图片理解；本次仅提取正文与表格，图片内容未纳入知识。')
        elif images and not options.get('vision'):
            warn(f'Word 包含 {len(images)} 张内嵌图片，本次仅识别图片文字；未开启图片理解，照片与图表的语义未纳入知识。')
        if options.get('ocr') or options.get('vision'):
            for index, part in enumerate(images):
                progress(f'处理 Word 图片 {index + 1}/{len(images)}', 15 + int(60 * (index + 1) / max(1, len(images))))
                raw = part.blob
                try:
                    image = Image.open(io.BytesIO(raw)); output = io.BytesIO(); image.convert('RGB').save(output, 'JPEG')
                    picture(output.getvalue(), f'文档图片 {index + 1}', f'image-{index + 1}.jpg')
                except (OSError, ValueError) as exc:
                    raise ValueError(f'Word 第 {index + 1} 张图片处理失败：{exc}') from None
    elif kind == 'pdf':
        try:
            with pdfplumber.open(path) as pdf:
                pages = len(pdf.pages)
                if pages > 200:
                    raise ValueError('PDF 超过 200 页，请拆分后上传')
                rendered = None
                try:
                    for index, page in enumerate(pdf.pages):
                        progress(f'解析 PDF 第 {index + 1}/{pages} 页', 10 + int(70 * (index + 1) / max(1, pages)))
                        text = page.extract_text(layout=False) or ''
                        add(f'第 {index + 1} 页', text, page=index + 1)
                        for ti, table in enumerate(page.extract_tables()):
                            add(f'第 {index + 1} 页 · 表格 {ti + 1}', table_markdown(table), 'table', page=index + 1)
                        scanned = len(text.strip()) < 20 and bool(page.images)
                        vector_graphics = bool(page.curves or page.rects or page.lines)
                        if scanned and not options.get('ocr'):
                            raise ValueError(f'第 {index + 1} 页是扫描页，请配置并开启云端 OCR 后重新解析')
                        if page.images and not (options.get('ocr') or options.get('vision')):
                            warn(f'PDF 第 {index + 1} 页包含图片，未开启 OCR 或图片理解；本次仅提取页面文字与表格，图片内容未纳入知识。')
                        elif page.images and not options.get('vision'):
                            warn(f'PDF 第 {index + 1} 页包含图片，本次仅识别图片文字；未开启图片理解，照片与图表的语义未纳入知识。')
                        if vector_graphics and not options.get('vision'):
                            warn(f'PDF 第 {index + 1} 页包含线条、曲线或色块等矢量图形，未开启图片理解；本次仅提取可读取的文字与表格，图形布局及图表语义未纳入知识。')
                        if scanned or (page.images and (options.get('ocr') or options.get('vision'))) or (vector_graphics and options.get('vision')) or options.get('forceOcr'):
                            if rendered is None:
                                rendered = pdfium.PdfDocument(str(path))
                            bitmap = rendered[index].render(scale=2)
                            output = io.BytesIO(); bitmap.to_pil().save(output, 'PNG'); bitmap.close()
                            picture(output.getvalue(), f'第 {index + 1} 页', f'page-{index + 1}.png', index + 1)
                finally:
                    if rendered is not None:
                        rendered.close()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF 无法读取，可能已加密或损坏：' + str(exc)[:160]) from None
    elif kind in ('png', 'jpg', 'jpeg', 'webp'):
        if not (options.get('ocr') or options.get('vision')):
            raise ValueError('图片需要开启 OCR 或视觉理解，请先配置对应模型')
        Image.open(path).verify()
        picture(path.read_bytes(), doc['name'], path.name)
        pages = 1
    elif kind in ('xlsx', 'xls', 'csv'):
        sheets = []
        if kind == 'xlsx':
            zip_guard(path)
            workbook = load_workbook(path, data_only=True, read_only=True)
            try:
                for sheet in workbook:
                    if (sheet.max_row or 0) > 50000 or (sheet.max_column or 0) > 500:
                        raise ValueError('工作表超过 50000 行或 500 列，请先拆分')
                    sheets.append((sheet.title, list(sheet.iter_rows(values_only=True))))
            finally:
                workbook.close()
        elif kind == 'xls':
            book = xlrd.open_workbook(str(path))
            try:
                for sheet in book.sheets():
                    if sheet.nrows > 50000 or sheet.ncols > 500:
                        raise ValueError('工作表过大，请先拆分')
                    sheets.append((sheet.name, [sheet.row_values(row) for row in range(sheet.nrows)]))
            finally:
                book.release_resources()
        else:
            text = decode(path.read_bytes())
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
            except csv.Error:
                dialect = csv.excel
            rows = list(csv.reader(io.StringIO(text), dialect))
            if len(rows) > 50000:
                raise ValueError('CSV 超过 50000 行，请先拆分')
            sheets = [(doc['name'], rows)]
        for sheet, rows in sheets:
            rows = [list(row) for row in rows if any(value is not None and str(value).strip() for value in row)]
            if not rows:
                continue
            header = rows[0]
            for start in range(1, max(2, len(rows)), 30):
                selected = rows[start:start + 30]
                add(f'{sheet} · 第 {start + 1}–{min(start + 30, len(rows))} 行', table_markdown([header] + selected), 'table', sheet=sheet, rowStart=start + 1, rowEnd=min(start + 30, len(rows)))
            pages += 1
    else:
        raise ValueError('不支持该文件格式')

    sources = [{'text': block.page_content, **{key: value for key, value in block.metadata.items() if value is not None}} for block in blocks]
    if extracted_blocks is not None:
        extracted_blocks.extend(sources)
    return split_blocks(sources, options, doc['id']), pages
