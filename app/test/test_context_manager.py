from contextlib import contextmanager


# @contextmanager
# def connect(url: str):
#     print(f"建立连接:{url}")
#     yield f"connection:{url}"
#     print(f"关闭连接:{url}")
#
#
# with connect("http://192.168.1.1:3306") as conn:
#     print(conn)


@contextmanager
def lifespan(app: str):
    print(f"数据库的初始化操作")
    yield f"运行{app}"
    print(f"数据库的关闭操作")


with lifespan("app") as app:
    print(app)