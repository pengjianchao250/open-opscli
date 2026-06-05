"""Open a SellerSprite browser session and capture JSON API traffic."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from opscli.config import CONFIG_DIR


DEFAULT_URL = "https://www.sellersprite.com/v3/keyword-miner/"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Capture SellerSprite JSON API traffic from a Playwright browser.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Initial URL to open.")
    parser.add_argument("--output-dir", default=None, help="Directory for captured request/response files.")
    parser.add_argument("--profile-dir", default=None, help="Persistent browser profile directory.")
    parser.add_argument("--channel", default="chrome", help="Browser channel, for example chrome or msedge.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser() if args.output_dir else _default_output_dir()
    profile_dir = Path(args.profile_dir).expanduser() if args.profile_dir else CONFIG_DIR / "seller_sprite" / "browser_profile"
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "manifest.jsonl"
    print(f"[seller-sprite-capture] output_dir={output_dir.resolve()}", flush=True)
    print(f"[seller-sprite-capture] profile_dir={profile_dir.resolve()}", flush=True)
    print("[seller-sprite-capture] close the browser or press Ctrl+C to stop.", flush=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        launch_options = {
            "headless": False,
            "viewport": {"width": 1440, "height": 1000},
            "accept_downloads": True,
        }
        if args.channel:
            launch_options["channel"] = args.channel
        executable_path = _fallback_browser_path(args.channel)
        if executable_path:
            launch_options.pop("channel", None)
            launch_options["executable_path"] = executable_path

        context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_options,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        async def capture_download(download) -> None:
            captured_at = datetime.now().isoformat(timespec="seconds")
            suggested = download.suggested_filename or "download.bin"
            index = len(list(output_dir.glob("download-*"))) + 1
            filename = f"download-{index:04d}-{_slug(suggested)}"
            output_path = output_dir / filename
            try:
                await download.save_as(output_path)
            except Exception:
                source_path = await download.path()
                if not source_path:
                    raise
                shutil.copy2(source_path, output_path)
            payload = {
                "captured_at": captured_at,
                "type": "download",
                "url": download.url,
                "suggested_filename": suggested,
                "path": str(output_path.resolve()),
            }
            _append_jsonl(manifest_path, payload)
            print(f"[download] {suggested} {download.url}", flush=True)

        async def capture_response(response) -> None:
            url = response.url
            parsed = urlparse(url)
            if "sellersprite.com" not in parsed.netloc.lower():
                return
            content_type = (response.headers.get("content-type") or "").lower()
            if "json" not in content_type and "/api/" not in parsed.path:
                return
            try:
                payload = await response.json()
            except Exception:
                return

            request = response.request
            captured_at = datetime.now().isoformat(timespec="seconds")
            slug = _slug(parsed.path)
            index = len(list(output_dir.glob("*.response.json"))) + 1
            prefix = f"{index:04d}-{datetime.now().strftime('%H%M%S')}-{slug}"
            request_path = output_dir / f"{prefix}.request.json"
            response_path = output_dir / f"{prefix}.response.json"

            request_payload = await _request_payload(request)
            request_path.write_text(
                json.dumps(
                    {
                        "captured_at": captured_at,
                        "method": request.method,
                        "url": url,
                        "headers": _safe_headers(request.headers),
                        "post_data": request_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            response_path.write_text(
                json.dumps(
                    {
                        "captured_at": captured_at,
                        "status": response.status,
                        "url": url,
                        "headers": response.headers,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            _append_jsonl(
                manifest_path,
                {
                    "captured_at": captured_at,
                    "method": request.method,
                    "status": response.status,
                    "url": url,
                    "request_file": str(request_path.resolve()),
                    "response_file": str(response_path.resolve()),
                },
            )
            print(f"[capture] {request.method} {response.status} {url}", flush=True)

        def attach_page(target_page) -> None:
            target_page.on("download", capture_download)

        context.on("response", capture_response)
        context.on("page", attach_page)
        for existing_page in context.pages:
            attach_page(existing_page)
        await page.goto(args.url, wait_until="domcontentloaded", timeout=120000)

        try:
            while len(context.pages) > 0:
                await asyncio.sleep(1)
        finally:
            await context.close()


async def _request_payload(request) -> object:
    post_data = request.post_data
    if not post_data:
        return None
    try:
        return json.loads(post_data)
    except json.JSONDecodeError:
        return post_data


def _default_output_dir() -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / "tmp-validation" / "seller-sprite-browser-capture" / run_id


def _fallback_browser_path(channel: str | None) -> str | None:
    candidates: list[str] = []
    if channel in {None, "", "chrome"}:
        candidates.extend(
            [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
        )
    if channel in {None, "", "msedge"}:
        candidates.extend(
            [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]
        )
    for command in ["chrome.exe", "msedge.exe"]:
        resolved = shutil.which(command)
        if resolved:
            candidates.append(resolved)
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    hidden = {"cookie", "authorization", "x-csrf-token"}
    return {key: ("<redacted>" if key.lower() in hidden else value) for key, value in headers.items()}


def _slug(path: str) -> str:
    text = path.strip("/").replace("/", "-") or "root"
    allowed = [char if char.isalnum() or char in {"-", "_"} else "-" for char in text]
    return "".join(allowed)[:80]


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
