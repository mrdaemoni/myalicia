#!/usr/bin/env python3
"""
Alicia — PDF Generation Skill

Converts Obsidian Markdown notes to clean, styled PDFs.
Supports vault notes, synthesis notes, podcast episodes, and any .md file.

Usage from Telegram:
  /pdf <note name or path>        — Generate PDF of a vault note
  /pdf S3E01                      — Fuzzy matches filenames
  /pdf Alicia/Wisdom/Synthesis/   — Generates PDFs for a whole folder

Dependencies: reportlab (pip install reportlab)
"""

import os
import re
import glob
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    HRFlowable, PageBreak
)
from myalicia.config import config

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_ROOT = str(config.vault.root)
PDF_OUTPUT_DIR = os.path.join(VAULT_ROOT, "Alicia", "PDFs")

# ── Styles ────────────────────────────────────────────────────────────────────

def _build_styles():
    """Build the PDF style sheet."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        'DocTitle', parent=styles['Title'],
        fontSize=22, leading=28, spaceAfter=4,
        textColor=HexColor('#1a1a1a'), alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        'DocSubtitle', parent=styles['Normal'],
        fontSize=14, leading=18, spaceAfter=20,
        textColor=HexColor('#555555'), alignment=TA_CENTER,
        fontName='Helvetica-Oblique',
    ))
    styles.add(ParagraphStyle(
        'MetaTag', parent=styles['Normal'],
        fontSize=10, leading=14, spaceAfter=6,
        textColor=HexColor('#888888'), alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    styles.add(ParagraphStyle(
        'SectionHead', parent=styles['Heading2'],
        fontSize=14, leading=18, spaceBefore=18, spaceAfter=8,
        textColor=HexColor('#2c3e50'), fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        'SubHead', parent=styles['Heading3'],
        fontSize=12, leading=16, spaceBefore=14, spaceAfter=6,
        textColor=HexColor('#34495e'), fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontSize=10.5, leading=15, spaceAfter=8,
        alignment=TA_JUSTIFY, fontName='Helvetica',
        textColor=HexColor('#222222'),
    ))
    styles.add(ParagraphStyle(
        'Quote', parent=styles['Normal'],
        fontSize=10.5, leading=15, spaceAfter=4,
        leftIndent=24, rightIndent=24,
        fontName='Helvetica-Oblique', textColor=HexColor('#333333'),
        alignment=TA_JUSTIFY,
    ))
    styles.add(ParagraphStyle(
        'SourceRef', parent=styles['Normal'],
        fontSize=9, leading=12, spaceAfter=8,
        leftIndent=24, textColor=HexColor('#777777'),
        fontName='Helvetica',
    ))
    styles.add(ParagraphStyle(
        'DebatePrompt', parent=styles['Normal'],
        fontSize=10, leading=14, spaceAfter=10,
        leftIndent=24, rightIndent=24,
        textColor=HexColor('#8e44ad'), fontName='Helvetica-Oblique',
    ))
    styles.add(ParagraphStyle(
        'NumberedItem', parent=styles['Normal'],
        fontSize=10.5, leading=15, spaceAfter=6,
        leftIndent=18, fontName='Helvetica', textColor=HexColor('#222222'),
    ))
    styles.add(ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontSize=8, leading=10,
        textColor=HexColor('#aaaaaa'), alignment=TA_CENTER,
    ))
    return styles


# ── Markdown → Flowables ─────────────────────────────────────────────────────

def _escape_xml(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph objects."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _md_inline(text: str) -> str:
    """Convert inline Markdown to ReportLab XML tags."""
    # Bold + italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic (careful not to match list bullets)
    text = re.sub(r'(?<!\w)\*([^*]+?)\*(?!\w)', r'<i>\1</i>', text)
    # Italic with underscore
    text = re.sub(r'(?<!\w)_([^_]+?)_(?!\w)', r'<i>\1</i>', text)
    # Inline code
    text = re.sub(r'`([^`]+?)`', r'<font face="Courier">\1</font>', text)
    # Wikilinks → just the display text
    text = re.sub(r'\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]', lambda m: m.group(2) or m.group(1), text)
    # Markdown links
    text = re.sub(r'\[([^\]]+?)\]\([^\)]+?\)', r'\1', text)
    return text


def _parse_markdown_to_flowables(md_text: str, styles) -> list:
    """
    Parse Markdown text into a list of ReportLab flowables.
    Handles: headings, blockquotes, numbered/bullet lists, horizontal rules,
    bold/italic inline, wikilinks, and plain paragraphs.
    """
    flowables = []
    lines = md_text.split('\n')
    i = 0
    title_extracted = False
    subtitle = None

    while i < len(lines):
        line = lines[i].rstrip()

        # Skip YAML frontmatter
        if i == 0 and line == '---':
            i += 1
            while i < len(lines) and lines[i].rstrip() != '---':
                i += 1
            i += 1
            continue

        # Empty line
        if not line.strip():
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^-{3,}$', line.strip()) or re.match(r'^\*{3,}$', line.strip()):
            flowables.append(HRFlowable(
                width="80%", thickness=0.5,
                color=HexColor('#cccccc'),
                spaceAfter=12, spaceBefore=12
            ))
            i += 1
            continue

        # Headings
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = _md_inline(_escape_xml(heading_match.group(2).strip()))

            if level == 1 and not title_extracted:
                # First H1 → title
                title_extracted = True
                flowables.append(Spacer(1, 40))
                flowables.append(Paragraph(text, styles['DocTitle']))
                # Check if next non-empty line is H2 (subtitle)
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    sub_match = re.match(r'^##\s+(.+)$', lines[j])
                    if sub_match:
                        sub_text = _md_inline(_escape_xml(sub_match.group(1).strip().strip('"')))
                        flowables.append(Paragraph(sub_text, styles['DocSubtitle']))
                        i = j + 1
                        continue
            elif level <= 2:
                flowables.append(Paragraph(text, styles['SectionHead']))
            else:
                flowables.append(Paragraph(text, styles['SubHead']))
            i += 1
            continue

        # Blockquote (can be multi-line)
        if line.startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote_lines.append(lines[i].strip().lstrip('>').strip())
                i += 1
            quote_text = _md_inline(_escape_xml(' '.join(quote_lines)))
            flowables.append(Paragraph(quote_text, styles['Quote']))
            continue

        # Numbered list item
        num_match = re.match(r'^(\d+)\.\s+(.+)$', line.strip())
        if num_match:
            num = num_match.group(1)
            text = _md_inline(_escape_xml(num_match.group(2)))
            flowables.append(Paragraph(f"{num}. {text}", styles['NumberedItem']))
            i += 1
            continue

        # Bullet list item
        bullet_match = re.match(r'^[-*]\s+(.+)$', line.strip())
        if bullet_match:
            text = _md_inline(_escape_xml(bullet_match.group(1)))
            flowables.append(Paragraph(f"&bull; {text}", styles['NumberedItem']))
            i += 1
            continue

        # Source/vault reference lines
        if line.strip().startswith('*Source:') or line.strip().startswith('*Vault:'):
            text = _md_inline(_escape_xml(line.strip().strip('*')))
            flowables.append(Paragraph(f"<i>{text}</i>", styles['SourceRef']))
            i += 1
            continue

        # Debate prompt lines
        if line.strip().startswith('**Debate prompt'):
            text = _md_inline(_escape_xml(
                re.sub(r'^\*\*Debate prompt:?\*\*\s*', '', line.strip())
            ))
            flowables.append(Paragraph(f"Debate prompt: {text}", styles['DebatePrompt']))
            i += 1
            continue

        # Regular paragraph — accumulate consecutive non-empty lines
        para_lines = []
        while i < len(lines) and lines[i].strip() and not re.match(r'^#{1,6}\s', lines[i]) \
                and not lines[i].strip().startswith('>') and not re.match(r'^-{3,}$', lines[i].strip()) \
                and not re.match(r'^\*{3,}$', lines[i].strip()) \
                and not re.match(r'^\d+\.\s', lines[i].strip()) \
                and not re.match(r'^[-*]\s', lines[i].strip()):
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            text = _md_inline(_escape_xml(' '.join(para_lines)))
            flowables.append(Paragraph(text, styles['Body']))
        continue

    return flowables


# ── Public API ────────────────────────────────────────────────────────────────

def find_vault_note(query: str) -> str:
    """
    Find a vault note by fuzzy name matching.
    Returns the full path, or None if not found.
    Uses the shared vault_resolver for robust matching.
    """
    try:
        from myalicia.skills.vault_resolver import resolve_note
        result = resolve_note(query)
        return result['path'] if result['found'] else None
    except ImportError:
        # Fallback if resolver not available
        query_lower = query.lower().strip()
        for root, dirs, files in os.walk(VAULT_ROOT):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.endswith('.md') and query_lower in f.lower():
                    return os.path.join(root, f)
        return None


def generate_pdf(md_path: str, output_path: str = None) -> str:
    """
    Generate a PDF from a Markdown file.

    Args:
        md_path: Full path to the .md file
        output_path: Optional output path. If None, saves next to the .md file.

    Returns:
        Path to the generated PDF.
    """
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    with open(md_path, encoding='utf-8') as f:
        md_text = f.read()

    # Determine output path
    if output_path is None:
        output_path = md_path.rsplit('.md', 1)[0] + '.pdf'

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    styles = _build_styles()
    flowables = _parse_markdown_to_flowables(md_text, styles)

    # Add footer
    flowables.append(Spacer(1, 30))
    flowables.append(HRFlowable(
        width="80%", thickness=0.5,
        color=HexColor('#cccccc'), spaceAfter=8, spaceBefore=8
    ))
    filename = os.path.basename(md_path).replace('.md', '')
    flowables.append(Paragraph(
        f"Generated by Alicia &bull; {datetime.now().strftime('%Y-%m-%d')} &bull; {filename}",
        styles['Footer']
    ))

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
    )
    doc.build(flowables)

    return output_path


def generate_pdf_from_query(query: str, same_folder: bool = True) -> dict:
    """
    Find a vault note by name and generate a PDF.
    This is the main entry point for the Telegram /pdf command.

    Args:
        query: Note name or path fragment (e.g., "S3E01", "quality-before-objects")
        same_folder: If True, save PDF in same folder as the .md file.
                     If False, save in Alicia/PDFs/

    Returns:
        dict with 'success', 'pdf_path', 'note_title', 'error'
    """
    note_path = find_vault_note(query)
    if not note_path:
        return {
            'success': False,
            'pdf_path': None,
            'note_title': None,
            'error': f"Could not find a note matching '{query}'"
        }

    note_title = os.path.basename(note_path).replace('.md', '')

    if same_folder:
        output_path = None  # generate_pdf will put it next to the .md
    else:
        os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(PDF_OUTPUT_DIR, f"{note_title}.pdf")

    try:
        pdf_path = generate_pdf(note_path, output_path)
        return {
            'success': True,
            'pdf_path': pdf_path,
            'note_title': note_title,
            'error': None
        }
    except Exception as e:
        return {
            'success': False,
            'pdf_path': None,
            'note_title': note_title,
            'error': str(e)
        }


def generate_folder_pdfs(folder_path: str) -> list:
    """
    Generate PDFs for all .md files in a folder.
    Returns list of result dicts.
    """
    full_path = os.path.join(VAULT_ROOT, folder_path) if not folder_path.startswith('/') else folder_path
    if not os.path.isdir(full_path):
        return [{'success': False, 'error': f"Folder not found: {folder_path}"}]

    results = []
    for f in sorted(os.listdir(full_path)):
        if f.endswith('.md'):
            md_path = os.path.join(full_path, f)
            try:
                pdf_path = generate_pdf(md_path)
                results.append({
                    'success': True,
                    'pdf_path': pdf_path,
                    'note_title': f.replace('.md', ''),
                })
            except Exception as e:
                results.append({
                    'success': False,
                    'note_title': f.replace('.md', ''),
                    'error': str(e),
                })
    return results
