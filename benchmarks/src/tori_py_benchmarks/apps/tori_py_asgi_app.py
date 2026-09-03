"""Native-ASGI Tori Py benchmark application."""

from tori_py import NestApplication
from tori_py.asgi import AsgiAdapter, asgi

from tori_py_benchmarks.apps.tori_py_common import BenchmarkModule


async def create_application() -> NestApplication:
    return await NestApplication.create(BenchmarkModule, adapter=AsgiAdapter())


application = asgi(create_application)
