#!/usr/bin/env python3
"""
E2E Production Test Script for markitdown-vision-service

Tests all PDF files in a given directory against the running service
and saves results for manual inspection.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx


def log(msg: str):
    """Print timestamped log message."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def wait_for_service(base_url: str, timeout: int = 30) -> bool:
    """Wait for service to be healthy."""
    log(f"Waiting for service at {base_url}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=5)
            if resp.status_code == 200:
                log("Service is healthy!")
                return True
        except httpx.RequestError:
            pass
        time.sleep(1)
    return False


def upload_pdf(
    client: httpx.Client,
    base_url: str,
    pdf_path: Path,
    describe_images: bool = True,
) -> dict:
    """Upload a PDF and return task info."""
    log(f"Uploading: {pdf_path.name} ({pdf_path.stat().st_size / 1024 / 1024:.2f} MB)")

    with open(pdf_path, "rb") as f:
        resp = client.post(
            f"{base_url}/tasks",
            params={"describe_images": str(describe_images).lower()},
            files={"file": (pdf_path.name, f, "application/pdf")},
            timeout=60,
        )

    if resp.status_code != 202:
        raise Exception(f"Upload failed: {resp.status_code} - {resp.text}")

    return resp.json()


def poll_task(
    client: httpx.Client,
    base_url: str,
    task_id: str,
    timeout: int = 300,
    poll_interval: int = 2,
) -> dict:
    """Poll task until completion or failure."""
    start = time.time()
    last_status = None

    while time.time() - start < timeout:
        resp = client.get(f"{base_url}/tasks/{task_id}", timeout=10)
        data = resp.json()
        status = data["status"]

        if status != last_status:
            log(f"  Task {task_id[:12]}... status: {status}")
            last_status = status

        if status in ("completed", "failed", "expired"):
            return data

        time.sleep(poll_interval)

    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


def download_outputs(
    client: httpx.Client,
    base_url: str,
    task_id: str,
    output_files: list[str],
    output_dir: Path,
) -> dict:
    """Download all output files and return paths."""
    task_output_dir = output_dir / task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)

    downloaded = {}
    for output_file in output_files:
        resp = client.get(
            f"{base_url}/tasks/{task_id}/files/{output_file}",
            timeout=30,
        )

        if resp.status_code == 200:
            file_path = task_output_dir / output_file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(resp.content)
            downloaded[output_file] = str(file_path)
        else:
            log(f"  Warning: Failed to download {output_file}: {resp.status_code}")

    return downloaded


def test_pdf(
    client: httpx.Client,
    base_url: str,
    pdf_path: Path,
    output_dir: Path,
    describe_images: bool = True,
    timeout: int = 300,
) -> dict:
    """Test a single PDF file end-to-end."""
    result = {
        "pdf_file": str(pdf_path),
        "pdf_name": pdf_path.name,
        "pdf_size_bytes": pdf_path.stat().st_size,
        "describe_images": describe_images,
        "success": False,
        "error": None,
        "task_id": None,
        "status": None,
        "duration_seconds": None,
        "output_files": [],
        "downloaded_files": {},
        "markdown_preview": None,
    }

    start_time = time.time()

    try:
        # Upload
        task_info = upload_pdf(client, base_url, pdf_path, describe_images)
        result["task_id"] = task_info["task_id"]

        # Poll for completion
        final_status = poll_task(client, base_url, task_info["task_id"], timeout)
        result["status"] = final_status["status"]
        result["duration_seconds"] = time.time() - start_time

        if final_status["status"] == "completed":
            result["success"] = True
            result["output_files"] = final_status.get("outputs", [])

            # Download outputs
            result["downloaded_files"] = download_outputs(
                client, base_url, task_info["task_id"],
                result["output_files"], output_dir
            )

            # Get markdown preview
            md_file = f"{task_info['task_id']}.md"
            if md_file in result["downloaded_files"]:
                md_path = Path(result["downloaded_files"][md_file])
                content = md_path.read_text(encoding="utf-8")
                result["markdown_preview"] = content[:2000] + ("..." if len(content) > 2000 else "")
                result["markdown_length"] = len(content)

            log(f"  Completed in {result['duration_seconds']:.1f}s - {len(result['output_files'])} files")
        else:
            result["error"] = final_status.get("error_message", "Unknown error")
            log(f"  Failed: {result['error']}")

    except Exception as e:
        result["error"] = str(e)
        result["duration_seconds"] = time.time() - start_time
        log(f"  Error: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(description="E2E test for markitdown-vision-service")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Service base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--input-dir",
        default="/home/frank/Workspaces/markitdown-vision-service/.claude/resources",
        help="Directory containing PDF files to test",
    )
    parser.add_argument(
        "--output-dir",
        default="/home/frank/Workspaces/markitdown-vision-service/e2e_results",
        help="Directory to save results",
    )
    parser.add_argument(
        "--no-describe",
        action="store_true",
        help="Disable image descriptions (faster)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout per PDF in seconds (default: 300)",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find PDF files
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        log(f"No PDF files found in {input_dir}")
        sys.exit(1)

    log(f"Found {len(pdf_files)} PDF files to test")
    log(f"Output directory: {output_dir}")
    log(f"Image descriptions: {'disabled' if args.no_describe else 'enabled'}")
    log("")

    # Wait for service
    if not wait_for_service(args.base_url):
        log("ERROR: Service not available")
        sys.exit(1)

    log("")

    # Test each PDF
    results = []
    with httpx.Client() as client:
        for i, pdf_path in enumerate(pdf_files, 1):
            log(f"[{i}/{len(pdf_files)}] Testing {pdf_path.name}")
            result = test_pdf(
                client,
                args.base_url,
                pdf_path,
                output_dir,
                describe_images=not args.no_describe,
                timeout=args.timeout,
            )
            results.append(result)
            log("")

    # Summary
    log("=" * 60)
    log("SUMMARY")
    log("=" * 60)

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    log(f"Total: {len(results)} | Passed: {len(successful)} | Failed: {len(failed)}")
    log("")

    if successful:
        log("Successful conversions:")
        for r in successful:
            images = len([f for f in r["output_files"] if f.startswith("images/")])
            log(f"  - {r['pdf_name']}: {r['duration_seconds']:.1f}s, {images} images, {r.get('markdown_length', 0)} chars")

    if failed:
        log("")
        log("Failed conversions:")
        for r in failed:
            log(f"  - {r['pdf_name']}: {r['error']}")

    # Save results JSON
    results_file = output_dir / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log("")
    log(f"Results saved to: {results_file}")

    # Create index HTML for easy viewing
    index_html = output_dir / "index.html"
    with open(index_html, "w") as f:
        f.write("""<!DOCTYPE html>
<html>
<head>
    <title>E2E Test Results</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        .success { color: green; }
        .failure { color: red; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background: #f5f5f5; }
        pre { background: #f5f5f5; padding: 10px; overflow-x: auto; max-height: 400px; }
        .task-link { font-family: monospace; }
    </style>
</head>
<body>
    <h1>E2E Test Results</h1>
    <p>Generated: """ + datetime.now().isoformat() + """</p>
    <table>
        <tr>
            <th>PDF</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Images</th>
            <th>Output</th>
        </tr>
""")
        for r in results:
            status_class = "success" if r["success"] else "failure"
            status_text = "✓ Success" if r["success"] else f"✗ {r['error']}"
            images = len([f for f in r.get("output_files", []) if f.startswith("images/")])
            duration = f"{r['duration_seconds']:.1f}s" if r['duration_seconds'] else "N/A"

            output_link = ""
            if r["task_id"] and r["success"]:
                md_path = f"{r['task_id']}/{r['task_id']}.md"
                output_link = f'<a href="{md_path}">View Markdown</a>'

            f.write(f"""        <tr>
            <td>{r['pdf_name']}<br><small>{r['pdf_size_bytes'] / 1024 / 1024:.2f} MB</small></td>
            <td class="{status_class}">{status_text}</td>
            <td>{duration}</td>
            <td>{images}</td>
            <td>{output_link}</td>
        </tr>
""")

        f.write("""    </table>
</body>
</html>
""")

    log(f"HTML index: {index_html}")

    # Exit with error code if any failed
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
