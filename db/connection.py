"""数据库连接管理"""
import psycopg2
from psycopg2 import OperationalError
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, log


def connect():
    """建立数据库连接，返回 connection 对象"""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    conn.autocommit = False
    return conn
