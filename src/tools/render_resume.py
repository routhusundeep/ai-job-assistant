"""Render the LaTeX master resume into a PDF."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer

DEFAULT_TEX = Path("data/resume.tex")
DEFAULT_CLS = Path("data/rewrite.cls")
DEFAULT_OUTPUT = Path("data/resume.pdf")
DEFAULT_ENGINE = "tectonic"
LOGGER = logging.getLogger(__name__)
app = typer.Typer(help="Compile the LaTeX resume into a PDF.")


def _configure_logging(log_level: Optional[str]) -> None:
    level = logging.INFO
    if log_level:
        parsed = getattr(logging, log_level.upper(), None)
        if not isinstance(parsed, int):
            raise typer.BadParameter(f"Invalid log level: {log_level}")
        level = parsed
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _copy_class_if_needed(tex_path: Path, cls_path: Path) -> Optional[Path]:
    """Ensure the LaTeX class file is available alongside the .tex."""
    if not cls_path.exists():
        raise FileNotFoundError(f"Class file not found at {cls_path}")
    target = tex_path.parent / cls_path.name
    if target.resolve() == cls_path.resolve():
        return None
    if target.exists():
        return target
    shutil.copy2(cls_path, target)
    return target


def _ensure_engine(engine: str) -> str:
    """Return the resolved engine path or raise a friendly error."""
    resolved = shutil.which(engine)
    if not resolved:
        raise FileNotFoundError(
            f"LaTeX engine '{engine}' not found on PATH. "
            "Install it via your package manager (e.g., `brew install tectonic`)."
        )
    return resolved


def _run_engine(engine: str, tex_path: Path, workdir: Path) -> Path:
    cmd = [
        engine,
        "--keep-intermediates",
        "--outdir",
        ".",
        tex_path.name,
    ]
    LOGGER.info("Running %s in %s: %s", engine, workdir, " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=workdir,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout:
        LOGGER.debug("tectonic stdout:\n%s", proc.stdout)
    if proc.stderr:
        LOGGER.debug("tectonic stderr:\n%s", proc.stderr)
    if proc.returncode != 0:
        message = (
            f"{engine} failed with code {proc.returncode}. "
            f"stdout: {proc.stdout.strip()} stderr: {proc.stderr.strip()}"
        )
        raise RuntimeError(message)
    return workdir / f"{tex_path.stem}.pdf"


def _clean_aux_files(workdir: Path, tex_stem: str) -> None:
    for ext in (".aux", ".log", ".out", ".toc"):
        candidate = workdir / f"{tex_stem}{ext}"
        if candidate.exists():
            try:
                candidate.unlink()
            except OSError:
                LOGGER.debug("Unable to remove %s", candidate)


def render_resume(
    tex_path: Path = DEFAULT_TEX,
    cls_path: Path = DEFAULT_CLS,
    output_pdf: Path = DEFAULT_OUTPUT,
    *,
    keep_aux: bool = False,
) -> Path:
    """Compile the resume .tex into a PDF using xelatex."""
    if not tex_path.exists():
        raise FileNotFoundError(f"Resume tex not found at {tex_path}")

    workdir = tex_path.parent
    workdir.mkdir(parents=True, exist_ok=True)

    copied_cls = None
    if cls_path:
        copied_cls = _copy_class_if_needed(tex_path, cls_path)

    resolved_engine = _ensure_engine(DEFAULT_ENGINE)

    try:
        generated_pdf = _run_engine(resolved_engine, tex_path, workdir)
    finally:
        if copied_cls and copied_cls.exists():
            try:
                copied_cls.unlink()
            except OSError:
                LOGGER.debug("Unable to remove temporary class file %s", copied_cls)

    if not generated_pdf.exists():
        raise FileNotFoundError(f"Expected PDF not found at {generated_pdf}")

    output_pdf = output_pdf.resolve()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    if generated_pdf.resolve() != output_pdf:
        shutil.move(generated_pdf, output_pdf)
        LOGGER.info("Moved PDF to %s", output_pdf)

    if not keep_aux:
        _clean_aux_files(workdir, tex_path.stem)

    return output_pdf


@app.command()
def main(
    tex: Path = typer.Option(DEFAULT_TEX, help="Path to the resume LaTeX file."),
    cls: Path = typer.Option(DEFAULT_CLS, help="Path to the resume class file."),
    output: Path = typer.Option(DEFAULT_OUTPUT, help="Destination PDF path."),
    keep_aux: bool = typer.Option(False, help="Keep auxiliary files (.aux, .log, .out)."),
    log_level: Optional[str] = typer.Option(
        None, help="Logging level (e.g., INFO, DEBUG)."
    ),
) -> None:
    """CLI entrypoint to render the resume PDF."""
    _configure_logging(log_level)
    pdf_path = render_resume(
        tex_path=tex,
        cls_path=cls,
        output_pdf=output,
        keep_aux=keep_aux,
    )
    typer.echo(f"Rendered PDF to {pdf_path}")


if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt:
        raise SystemExit(1)
