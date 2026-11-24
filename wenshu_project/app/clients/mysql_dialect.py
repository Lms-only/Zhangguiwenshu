"""修复 SQLAlchemy aiomysql 方言的池 pre-ping 兼容问题。

问题链路：
- SQLAlchemy 2.0.46 的 mysql+pymysql 方言在 ``MySQLDialect_pymysql.do_ping()``
  中会根据 PyMySQL ``ping()`` 的默认值决定是否显式传 ``reconnect`` 参数；
- 当前 PyMySQL 的签名是 ``ping(self, reconnect=False)``，默认值已经是 False，
  因此 ``do_ping()`` 走的是无参分支 ``dbapi_connection.ping()``；
- 但 aiomysql 方言的连接包装类
  ``AsyncAdapt_aiomysql_connection.ping(self, reconnect)`` 要求必须传
  ``reconnect``，于是 pool_pre_ping 复用连接时抛出
  ``TypeError: ... ping() missing 1 required positional argument: 'reconnect'``。

修复方式：重写 ``do_ping()``，固定传 ``False``。pre-ping 只做存活检测，
本来就不应该重连；aiomysql 适配层的 ``assert not reconnect`` 也要求为 False。
"""

from sqlalchemy.dialects.mysql.aiomysql import MySQLDialect_aiomysql
from sqlalchemy.engine.interfaces import DBAPIConnection


class MySQLDialect_aiomysql_preping(MySQLDialect_aiomysql):
    """显式给 aiomysql 适配层的 ping() 传 reconnect=False。"""

    # 父类 pymysql 方言已支持语句缓存。SQLAlchemy 会检查
    # __class__.__dict__，子类需显式声明，否则误报未开启缓存。
    supports_statement_cache = True

    def do_ping(self, dbapi_connection: DBAPIConnection) -> bool:
        dbapi_connection.ping(False)  # type: ignore[attr-defined]
        return True
