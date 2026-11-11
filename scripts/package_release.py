import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca_flow import __version__


def main():
    target = ROOT / "dist" / f"OrcaFlow-{__version__}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    files = [ROOT / name for name in ("README.md", "LICENSE", "CHANGELOG.md", "pyproject.toml", "iniciar.pyw", ".gitignore")]
    for folder in ("orca_flow", "tests", "scripts", "examples", "assets"):
        files.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, Path("OrcaFlow") / path.relative_to(ROOT))
    print(target)


if __name__ == "__main__":
    main()
