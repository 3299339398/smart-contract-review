"""文档解析器模块 —— 根据文件扩展名创建对应的解析器。"""

import os
import logging

logger = logging.getLogger(__name__)


class DocumentParser:
    """文档解析器基类。"""
    def extract_text(self, file_path: str) -> str:
        raise NotImplementedError


class DocumentParserFactory:
    """解析器工厂：根据文件扩展名创建对应的解析器实例。"""

    @staticmethod
    def create(file_path: str) -> DocumentParser:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.pdf':
            from app.parser.pdf_parser import PdfParser
            return PdfParser()
        elif ext in ('.docx', '.doc'):
            from app.parser.docx_parser import DocxParser
            return DocxParser()
        elif ext == '.txt':
            return TxtParser()
        else:
            raise ValueError(f"不支持的文件类型: {ext}")


class TxtParser(DocumentParser):
    """纯文本解析器：直接读取文件内容。"""
    def extract_text(self, file_path: str) -> str:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
