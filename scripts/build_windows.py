import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                    "--windowed", "--noupx", "--name", "OrcaFlow", "--distpath", str(ROOT / "dist"),
                    "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"), str(ROOT / "iniciar.pyw")], cwd=ROOT, check=True)
    target = ROOT / "dist" / "OrcaFlow.exe"
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (ROOT / "dist" / "SHA256SUMS.txt").write_text(f"{digest}  {target.name}\n", encoding="ascii")
    print(target)


if __name__ == "__main__":
    main()
