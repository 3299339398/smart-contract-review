import os

# 魔术字节签名
PDF_SIGNATURE = b"%PDF"
DOCX_SIGNATURE = b"PK\x03\x04"
DOC_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

SIZE_LIMITS = {
    "PDF": 20 * 1024 * 1024,
    "DOCX": 10 * 1024 * 1024,
    "DOC": 10 * 1024 * 1024,
    "TXT": 5 * 1024 * 1024,
}

MIME_ALLOW = {
    "PDF": {"application/pdf"},
    "DOCX": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "DOC": {"application/msword"},
    "TXT": {"text/plain"},
}

EXT_TO_TYPE = {
    ".pdf": "PDF", ".docx": "DOCX", ".doc": "DOC", ".txt": "TXT",
}


def detect_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return EXT_TO_TYPE.get(ext, "UNKNOWN")


def validate(file_bytes: bytes, filename: str, content_type: str = None) -> str:
    """六层校验。返回检测到的文件类型，校验失败抛出 ValueError。"""

    # 1. 文件名合法性检查
    if not filename or not filename.strip():
        raise ValueError("文件名不能为空")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError("文件名包含非法字符")

    # 2. 文件非空检查
    if not file_bytes:
        raise ValueError("文件为空，请上传有效文件")

    # 3. 扩展名必须可识别
    file_type = detect_type(filename)
    if file_type == "UNKNOWN":
        raise ValueError(f"不支持的文件类型: {filename}，仅支持 PDF、DOCX、DOC、TXT 格式")

    # 4. 按类型限制文件大小
    limit = SIZE_LIMITS.get(file_type, 5 * 1024 * 1024)
    if len(file_bytes) > limit:
        raise ValueError(
            f"文件大小超出限制: {file_type} 文件最大 {limit // (1024 * 1024)} MB，"
            f"当前 {len(file_bytes) / (1024 * 1024):.1f} MB"
        )

    # 5. MIME 类型校验（尽力而为）
    if content_type:
        mime_ok = False
        if file_type == "DOCX":
            mime_ok = "officedocument" in content_type or "zip" in content_type
        elif file_type == "DOC":
            mime_ok = "msword" in content_type or "octet-stream" in content_type
        elif file_type == "PDF":
            mime_ok = content_type == "application/pdf"
        elif file_type == "TXT":
            mime_ok = content_type.startswith("text/")
        if not mime_ok:
            raise ValueError(
                f"文件类型不匹配: 扩展名表明 {file_type} 文件，但 MIME 类型为 {content_type}"
            )

    # 6. 魔术字节校验
    if file_type != "TXT":
        if file_type == "PDF" and not file_bytes.startswith(PDF_SIGNATURE):
            raise ValueError(f"文件内容与扩展名不符: '{filename}' 的文件头不是有效的 PDF 格式")
        elif file_type == "DOCX" and not file_bytes.startswith(DOCX_SIGNATURE):
            raise ValueError(f"文件内容与扩展名不符: '{filename}' 的文件头不是有效的 DOCX 格式")
        elif file_type == "DOC":
            if file_bytes.startswith(DOCX_SIGNATURE):
                raise ValueError(
                    f"文件 '{filename}' 实际为 DOCX 格式，请将扩展名改为 .docx 后重新上传"
                )
            if not file_bytes.startswith(DOC_SIGNATURE):
                raise ValueError(f"文件内容与扩展名不符: '{filename}' 的文件头不是有效的 DOC 格式")
    else:
        # TXT：检查是否包含二进制内容
        check_bytes = file_bytes[:512]
        if check_bytes and _contains_binary(check_bytes):
            raise ValueError(
                f"文件 '{filename}' 包含非文本内容，无法作为 TXT 文件处理"
            )

    return file_type


def _contains_binary(data: bytes) -> bool:
    suspicious = 0
    for b in data:
        v = b
        if v == 0:
            return True
        if v < 0x09:
            return True
        if v in (0x0B, 0x0C):
            return True
        if v > 0x7E and v < 0xC0:
            suspicious += 1
    return suspicious > len(data) * 0.1
