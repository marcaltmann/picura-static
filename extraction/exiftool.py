import json
import subprocess

# The archive pass reads from stdin ('-'), emits JSON ('-j') with raw numeric
# values ('-n'), and drops the filesystem ('File') and tool ('ExifTool') tag
# groups so the result is image metadata only.
_ARCHIVE_COMMAND = ['exiftool', '-j', '-n', '--File:all', '--ExifTool:all', '-']

# The lens pass deliberately omits '-n': the Nikon LensID is a composite tag
# decoded against ExifTool's lens database via its print conversion. With '-n'
# that lookup is skipped and only the raw hex key (e.g. 'B2 00 5C 80 ...') is
# returned, so the lens name must be read in print-conversion mode.
_LENS_COMMAND = ['exiftool', '-j', '-LensID', '-LensModel', '-Lens', '-']

_TIMEOUT = 30


def _invoke(command: list[str], data: bytes) -> dict:
    # Exceptions are caught one type per clause on purpose: ruff format
    # currently rewrites multi-type ``except (A, B):`` tuples into invalid
    # syntax, so the parenthesised form cannot be used here.
    try:
        proc = subprocess.run(
            command, input=data, capture_output=True, timeout=_TIMEOUT
        )
    except OSError:
        return {}
    except subprocess.SubprocessError:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        parsed = json.loads(proc.stdout)
    except ValueError:
        return {}
    if not parsed:
        return {}
    result = parsed[0]
    result.pop('SourceFile', None)
    return result


def run_exiftool(data: bytes) -> dict:
    return _invoke(_ARCHIVE_COMMAND, data)


def extract_lens(data: bytes) -> dict:
    return _invoke(_LENS_COMMAND, data)
