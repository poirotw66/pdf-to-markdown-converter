"""Local E2E: POST documents to the convert API and save Markdown locally.

Run as a real file (not stdin) so multiprocessing inside the app works on macOS.

Single file: one conversion, optional preview.
Batch: scan a folder and convert in parallel with a thread pool (each worker runs asyncio + AsyncClient; ASGITransport is async-only in recent httpx).
"""
from __future__ import annotations

import argparse
import asyncio
import mimetypes
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx"})
_print_lock = threading.Lock()


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if suffix == ".pdf":
        return "application/pdf"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _resolve_under_root(path: Path) -> Path:
    if path.is_absolute():
        return path
    return _ROOT / path


def collect_batch_files(directory: Path, recursive: bool) -> list[Path]:
    """Return sorted list of supported files under directory."""
    if not directory.is_dir():
        return []
    if recursive:
        candidates = directory.rglob("*")
    else:
        candidates = directory.iterdir()
    files = [
        p
        for p in candidates
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda p: str(p).lower())


def convert_one(
    doc_path: Path,
    output_path: Path,
    timeout_seconds: float,
    preview_chars: int,
    quiet: bool,
    force: bool = False,
) -> tuple[int, str]:
    """
    Convert one file via ASGI app; write Markdown to output_path.

    Returns:
        (exit_code, message) where exit_code 0 ok or skipped, 1 missing file, 2 HTTP error
    """
    if not doc_path.is_file():
        msg = f"missing_file {doc_path.resolve()}"
        if not quiet:
            with _print_lock:
                print(msg)
        return 1, msg

    if not force and output_path.is_file():
        msg = f"skipped_existing {output_path.resolve()}"
        if not quiet:
            with _print_lock:
                print(f"[{doc_path.name}] skip: output already exists -> {output_path.resolve()}")
        return 0, msg

    payload = doc_path.read_bytes()
    mime = _guess_mime(doc_path)
    form: dict[str, str] = {}
    key = (settings.google_api_key or "").strip()
    if key:
        form["api_key"] = key

    async def _post() -> object:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            timeout=timeout_seconds,
        ) as client:
            files = {"file": (doc_path.name, payload, mime)}
            return await client.post("/api/v1/convert-pdf", files=files, data=form)

    response = asyncio.run(_post())

    if not quiet:
        with _print_lock:
            print(f"[{doc_path.name}] status_code={response.status_code}")

    if response.status_code == 200:
        text = response.text
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        if not quiet:
            with _print_lock:
                print(f"[{doc_path.name}] saved_markdown {output_path.resolve()} chars={len(text)}")
                if preview_chars > 0:
                    print(f"[{doc_path.name}] --- preview ---")
                    print(text[:preview_chars])
        return 0, "ok"

    try:
        body = response.json()
        msg = str(body)
    except Exception:
        msg = response.text[:800]
    if not quiet:
        with _print_lock:
            print(f"[{doc_path.name}] error {msg}")
    return 2, msg


def _batch_worker(
    doc_path: Path,
    output_dir: Path | None,
    timeout_seconds: float,
    quiet: bool,
    force: bool,
) -> tuple[Path, int, str]:
    if output_dir is not None:
        out_path = output_dir / f"{doc_path.stem}.md"
    else:
        out_path = doc_path.parent / f"{doc_path.stem}.md"
    code, msg = convert_one(
        doc_path,
        out_path,
        timeout_seconds,
        preview_chars=0,
        quiet=quiet,
        force=force,
    )
    return doc_path, code, msg


def run_batch(
    directory: Path,
    output_dir: Path | None,
    workers: int,
    timeout_seconds: float,
    recursive: bool,
    quiet: bool,
    force: bool,
) -> int:
    files = collect_batch_files(directory, recursive=recursive)
    if not files:
        print(f"No supported files found in {directory.resolve()} (extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))})")
        return 1

    print(f"Batch: {len(files)} file(s), workers={workers}, dir={directory.resolve()}")
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Output directory: {output_dir.resolve()}")

    failures: list[tuple[Path, int, str]] = []
    results: list[tuple[Path, int, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(
                _batch_worker,
                path,
                output_dir,
                timeout_seconds,
                quiet,
                force,
            ): path
            for path in files
        }
        for future in as_completed(future_map):
            results.append(future.result())

    converted = 0
    skipped = 0
    for doc_path, code, msg in results:
        if code == 0 and msg.startswith("skipped_existing"):
            skipped += 1
            if quiet:
                print(f"SKIP {doc_path.name}")
            continue
        if code == 0:
            converted += 1
            if quiet:
                print(f"OK {doc_path.name}")
            continue
        failures.append((doc_path, code, msg))

    print(
        f"\nSummary: converted={converted}, skipped={skipped}, failed={len(failures)}, total={len(files)}"
    )
    if failures:
        print(f"Failures ({len(failures)}):")
        for path, code, msg in failures:
            print(f"  - {path.name} (code={code}): {msg[:200]}")
        return 2

    if converted == 0 and skipped == len(files):
        print("All files skipped (output already exists). Use --force to overwrite.")
    elif skipped:
        print("Done (some outputs were skipped because they already exist; use --force to overwrite).")
    else:
        print("All files converted successfully.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert PDF/DOCX/PPTX via local ASGI app and write Markdown to disk.",
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=None,
        help="Path to one .pdf, .docx, or .pptx (relative to project root if not absolute). Omit when using --batch-dir.",
    )
    parser.add_argument(
        "--batch-dir",
        type=str,
        default=None,
        help="Convert all supported files in this directory (use with --workers for parallel runs).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="With --batch-dir, include subfolders (rglob).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Thread pool size for --batch-dir (default: 4).",
    )
    parser.add_argument(
        "--batch-output-dir",
        type=str,
        default=None,
        help="With --batch-dir, write all .md files here (default: next to each source file).",
    )
    parser.add_argument(
        "--save-intermediate-pdf-dir",
        type=str,
        default=None,
        help=(
            "If set, save the intermediate PDF produced by DOCX/PPTX -> PDF conversion "
            "to this directory (overrides OFFICE_INTERMEDIATE_PDF_SAVE_DIR for this run)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Single-file only: output .md path (default: same directory as input, stem + .md)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="HTTP client timeout in seconds (default: 900)",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Single-file only: do not print a preview of the Markdown body",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=2000,
        help="Single-file only: max preview characters (default: 2000)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Batch only: print only summary lines (less interleaved detail per file).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output .md if present (default: skip when same path exists).",
    )
    args = parser.parse_args()

    if args.save_intermediate_pdf_dir:
        settings.office_intermediate_pdf_save_dir = str(
            _resolve_under_root(Path(args.save_intermediate_pdf_dir))
        )

    if args.batch_dir:
        batch_path = _resolve_under_root(Path(args.batch_dir))
        out_dir: Path | None = None
        if args.batch_output_dir:
            out_dir = _resolve_under_root(Path(args.batch_output_dir))
        if args.input_file:
            print("Warning: positional input_file is ignored when --batch-dir is set.", file=sys.stderr)
        raise SystemExit(
            run_batch(
                directory=batch_path,
                output_dir=out_dir,
                workers=args.workers,
                timeout_seconds=args.timeout,
                recursive=args.recursive,
                quiet=args.quiet,
                force=args.force,
            )
        )

    input_name = args.input_file if args.input_file is not None else "扣薪入門_20251015.docx"
    doc_path = _resolve_under_root(Path(input_name))

    if args.output:
        out_path = _resolve_under_root(Path(args.output))
    else:
        out_path = doc_path.parent / f"{doc_path.stem}.md"

    preview_chars = 0 if args.no_preview else max(0, args.preview_chars)
    code, msg = convert_one(
        doc_path,
        out_path,
        args.timeout,
        preview_chars,
        quiet=False,
        force=args.force,
    )
    if code == 0 and msg.startswith("skipped_existing"):
        print(msg)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
