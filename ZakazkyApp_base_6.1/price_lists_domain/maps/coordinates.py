"""Load immutable PROJ reference data without shipping loose .db update files.

Existing safe TURTO updaters reject every loose database file in a payload.
Keep PROJ's *reference* database in an archive, as with the Offer Engine's
sources. It is extracted into a private process directory, never the CRM data.
"""
from functools import lru_cache
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import zipfile

_reference_directory = None


@lru_cache(maxsize=1)
def transformer():
    global _reference_directory
    reference = None
    if getattr(sys,'frozen',False):
        archive = Path(sys._MEIPASS) / 'proj_reference_bundle.zip'
        _reference_directory = tempfile.TemporaryDirectory(prefix='turto-proj-',ignore_cleanup_errors=True)
        reference = Path(_reference_directory.name)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path = PurePosixPath(member.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in member.filename or member.file_size > 30_000_000:
                    raise ValueError('Neplatná referenční data pro souřadnice.')
                if member.is_dir(): continue
                target = reference.joinpath(*path.parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(bundle.read(member))
        if not (reference/'proj.db').is_file():
            raise ValueError('V instalaci chybí referenční data souřadnic.')
        # Set before importing pyproj: its native context is initialized at import.
        os.environ['PROJ_DATA'] = str(reference)
        os.environ['PROJ_LIB'] = str(reference)
    from pyproj import Transformer, datadir
    if reference: datadir.set_data_dir(str(reference))
    return Transformer.from_crs('EPSG:5514','EPSG:4326',always_xy=True)
