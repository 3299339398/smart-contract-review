"""密码安全工具 —— bcrypt 哈希与验证。"""

import bcrypt


def hash_password(password: str) -> str:
    """对密码做 bcrypt 哈希，返回哈希字符串。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """验证密码是否与 bcrypt 哈希匹配。"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
