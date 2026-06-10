"""Single source of truth for Waterdrop's version.

On a tagged release the build (`.github/workflows/build.yml`) rewrites this file
with the tag's version, so the packaged app reports the same number shown on the
release and in the download's file name.
"""

__version__ = "1.0.0"
