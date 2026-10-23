"""PDF 解析器 —— 基于 PyMuPDF (fitz) 提取文本，保留表格行结构。"""

import logging
from app.parser.document_parser import DocumentParser

logger = logging.getLogger(__name__)

# 同表格行的 y 坐标容差（点数），在此范围内的块视为同一行
TABLE_ROW_Y_TOLERANCE = 5.0


class PdfParser(DocumentParser):
    """PDF 文档解析器：使用 PyMuPDF 按页提取文本块，按位置排序后拼接。
    检测表格结构：同一 y 坐标上的多个块用 "|" 连接，保留行列关系。
    """

    def extract_text(self, file_path: str) -> str:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text_parts = []
            for page in doc:
                blocks = page.get_text("blocks")
                # 按 y 坐标，再按 x 坐标排序
                blocks.sort(key=lambda b: (b[1], b[0]))
                text_parts.extend(self._process_page_blocks(blocks))
            doc.close()
            return "\n\n".join(text_parts)

        except ImportError:
            logger.warning("PyMuPDF 未安装，使用 pdftotext 命令行工具作为后备")
            return self._fallback_extract(file_path)

    def _process_page_blocks(self, blocks: list) -> list[str]:
        """处理单页的文本块，将同 y 坐标相邻块合并为表格行。"""
        parts = []
        row_blocks = []   # 同一表格行中的块
        row_y = None

        for block in blocks:
            text = block[4].strip()
            if not text or len(text) <= 3:
                continue

            y = block[1]
            x = block[0]

            if row_y is not None and abs(y - row_y) <= TABLE_ROW_Y_TOLERANCE:
                # 同一行，追加到行缓冲
                row_blocks.append((x, text))
            else:
                # 新行开始，先 flush 上一行
                if row_blocks:
                    parts.append(self._format_row(row_blocks))
                # 开始新行
                row_blocks = [(x, text)]
                row_y = y

        # flush 最后一行的缓冲
        if row_blocks:
            parts.append(self._format_row(row_blocks))

        return parts

    def _format_row(self, row_blocks: list[tuple[float, str]]) -> str:
        """格式化表格行：单列直接返回文本，多列用 "|" 拼接。"""
        # 按 x 坐标排序
        row_blocks.sort(key=lambda item: item[0])
        if len(row_blocks) == 1:
            return row_blocks[0][1]
        # 多列 → 表格行
        return " | ".join(text for _, text in row_blocks)

    def _fallback_extract(self, file_path: str) -> str:
        """后备方案：调用系统 pdftotext 命令行工具。"""
        try:
            import subprocess
            result = subprocess.run(['pdftotext', file_path, '-', '-layout'],
                                    capture_output=True, text=True)
            return result.stdout
        except Exception:
            return f"[无法解析的 PDF 内容: {file_path}]"
