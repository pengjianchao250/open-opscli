"""隔离进程测量分页、流式导出和沉淀读取；使用合成宽行与上传替身。"""

import asyncio
import ctypes
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from opscli.seller_sprite.collection_storage_parser import SellerSpriteCollectionParser
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services import api_manager
from opscli.shared.collection_storage.models import CollectionSubmission
from tests.seller_sprite.test_api_manager import DummyAccountProvider, DummyApiClient
from tests.seller_sprite.test_product_pagination import response


def rss_bytes() -> int:
    """使用 Windows 系统接口获取当前 Python 工作集，不包含浏览器。"""
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize


def main(total: int) -> None:
    """采样全过程 RSS，并输出可比较的 JSON 指标。"""
    api_manager.SellerSpriteApiClient = DummyApiClient

    def upload(**kwargs):
        """模拟已有上传路径逐块读取文件。"""
        with Path(kwargs["export"].path).open("rb") as stream:
            while stream.read(64 * 1024):
                pass
        kwargs["export"].url = "https://example.invalid/test.xlsx"

    async def browser(**kwargs):
        result = response(total, kwargs["payload"]["page"])
        for item in result["data"]["items"]:
            item.update(
                title=(item["title"] + "办公家具与家用收纳 ") * 40,
                brand="测试品牌",
                overviews={"材质": "合成数据" * 100},
                nodeLabelPath="Home & Kitchen > Furniture",
                amzUnit=12345,
                reviewsRate=0.12,
                totalAmount=10000.25,
                parent="B000PARENT",
            )
        return SimpleNamespace(response=result, warnings=[])

    api_manager._upload_export_if_enabled = upload
    api_manager._run_browser_route_request = browser
    baseline = rss_bytes()
    samples = [baseline]
    stop = threading.Event()

    def sample() -> None:
        """每10毫秒采样一次，保留峰值而非整个时间序列。"""
        while not stop.wait(0.01):
            samples[0] = max(samples[0], rss_bytes())

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(
            prefix="seller-pagination-bench-"
        ) as directory:
            root = Path(directory)
            manager = api_manager.SellerSpriteApiManager(
                settings=SellerSpriteSettings(output_dir=root),
                account_provider=DummyAccountProvider(),
            )
            result = asyncio.run(
                manager.run(
                    SellerSpriteScenarioRequest(
                        scenario="product-research",
                        site="US",
                        period="30d",
                        job_id="bench",
                        collection_scope="all",
                        mode="browser-route",
                    )
                )
            )
            parsed = SellerSpriteCollectionParser().parse(
                CollectionSubmission(
                    source_system="seller_sprite",
                    source_job_id="bench",
                    producer_service="benchmark",
                    scenario="product-research",
                    site="US",
                    data_environment="debug",
                    ingestion_mode="live",
                    result_path=result.result_path,
                )
            )
            consumed = sum(1 for record in parsed.datasets[0].records)
            assert consumed == min(total, 2000)
            metrics = {
                "rows": consumed,
                "baseline_rss_mib": round(baseline / 2**20, 2),
                "peak_rss_mib": round(max(samples[0], rss_bytes()) / 2**20, 2),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "xlsx_bytes": Path(result.export.path).stat().st_size,
                "result_bytes": Path(result.result_path).stat().st_size,
                "disk_bytes": sum(
                    path.stat().st_size for path in root.rglob("*") if path.is_file()
                ),
                "browser_rss": "not_measured",
                "data_source": "synthetic",
            }
    finally:
        stop.set()
        thread.join()
    print(json.dumps(metrics))


if __name__ == "__main__":
    main(int(sys.argv[1]))
