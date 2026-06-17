import psycopg
from psycopg.rows import dict_row

from meu_robo.config import get_database_url


def get_connection():
    return psycopg.connect(get_database_url(), row_factory=dict_row)
