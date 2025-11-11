"""
ABOUTME: Converts Grinold-Kahn PDF to structured markdown files
ABOUTME: Extracts by chapter and organizes for knowledge graph integration
"""
import fitz  # PyMuPDF
import re
from pathlib import Path
from typing import List, Tuple, Dict

def extract_chapter_structure(doc: fitz.Document) -> List[Tuple[int, str, int]]:
    """Extract chapter structure from PDF"""
    chapters = []
    toc = doc.get_toc()

    # Filter for actual chapter headings (looking for patterns like "Chapter N")
    for level, title, page in toc:
        # Skip deep nested levels and file names
        if level > 2 or 'nlreader' in title.lower() or 'binder' in title.lower() or 'pdf' in title.lower():
            continue
        if title.strip():
            chapters.append((level, title, page))

    return chapters

def clean_text(text: str) -> str:
    """Clean extracted text for markdown"""
    # Remove excessive whitespace
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    # Fix hyphenation at line breaks
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
    # Clean up spacing
    text = text.strip()
    return text

def extract_page_text(page: fitz.Page) -> str:
    """Extract text from a page"""
    text = page.get_text()
    return clean_text(text)

def convert_pdf_to_markdown_chunks(pdf_path: str, output_dir: str, chunk_size: int = 20):
    """Convert PDF to markdown in chunks"""
    doc = fitz.open(pdf_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    total_pages = len(doc)
    print(f"Converting {total_pages} pages to markdown...")

    # Extract by chunks
    for start_page in range(0, total_pages, chunk_size):
        end_page = min(start_page + chunk_size, total_pages)
        chunk_num = (start_page // chunk_size) + 1

        chunk_text = []
        chunk_text.append(f"# Grinold-Kahn Active Portfolio Management\n")
        chunk_text.append(f"## Pages {start_page + 1}-{end_page}\n\n")

        for page_num in range(start_page, end_page):
            page = doc[page_num]
            text = extract_page_text(page)

            if text:
                chunk_text.append(f"### Page {page_num + 1}\n\n")
                chunk_text.append(text)
                chunk_text.append("\n\n---\n\n")

        # Save chunk
        chunk_filename = f"grinold_kahn_chunk_{chunk_num:03d}_pages_{start_page+1:03d}-{end_page:03d}.md"
        chunk_path = output_path / chunk_filename

        with open(chunk_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(chunk_text))

        print(f"  Created {chunk_filename}")

    print(f"\nConversion complete! {(total_pages + chunk_size - 1) // chunk_size} chunks created in {output_dir}")

    # Create index
    create_index(output_path, total_pages, chunk_size)

def create_index(output_dir: Path, total_pages: int, chunk_size: int):
    """Create an index markdown file"""
    index_lines = [
        "# Grinold-Kahn Active Portfolio Management - Markdown Index\n",
        f"**Total Pages**: {total_pages}\n",
        f"**Chunk Size**: {chunk_size} pages per file\n\n",
        "## Chunks\n\n"
    ]

    for start_page in range(0, total_pages, chunk_size):
        end_page = min(start_page + chunk_size, total_pages)
        chunk_num = (start_page // chunk_size) + 1
        chunk_filename = f"grinold_kahn_chunk_{chunk_num:03d}_pages_{start_page+1:03d}-{end_page:03d}.md"

        index_lines.append(f"- [{chunk_filename}](./{chunk_filename}) - Pages {start_page+1}-{end_page}\n")

    with open(output_dir / "INDEX.md", 'w', encoding='utf-8') as f:
        f.write(''.join(index_lines))

    print(f"Created INDEX.md")

if __name__ == "__main__":
    pdf_path = "docs/books/Grinold-Kahn-Active-Portfolio-Management-1999.pdf"
    output_dir = "docs/books/grinold_kahn_markdown"
    chunk_size = 20  # 20 pages per chunk = ~31 files

    convert_pdf_to_markdown_chunks(pdf_path, output_dir, chunk_size)
