"""
MkDocs hook: serve CONTRIBUTING.md and CHANGELOG.md from the repo root as pages
of the docs site, without a second copy to keep in sync.

MkDocs only reads files under docs_dir. Symlinks would work on Linux, but they
degrade to plain text files on a Windows checkout without core.symlinks, and a
copy would drift. Registering generated files at build time avoids both - the
root files stay the single source of truth, and no extra plugin is needed.
"""
from pathlib import Path

from mkdocs.structure.files import File

_ROOT_PAGES = {
    "contributing.md": "CONTRIBUTING.md",
    "changelog.md": "CHANGELOG.md",
}


def on_files(files, config):
    root = Path(config.config_file_path).resolve().parent
    for page, source in _ROOT_PAGES.items():
        content = (root / source).read_text(encoding="utf-8")
        files.append(File.generated(config, page, content=content))
    return files
