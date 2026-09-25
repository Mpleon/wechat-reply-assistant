# Third-party notices

`vendor/wechatauto/` contains source snapshots from **fanyuantaier/wechatauto-replica**, used under the Apache License, Version 2.0. The original license is included at `vendor/wechatauto/LICENSE`; source location and snapshot checksums are documented in that directory.

Runtime dependencies are listed in `requirements.txt` and retain their respective licenses. They are installed separately and their binaries are not committed to this repository.

Desktop releases bundle the Python runtime and dependencies from requirements-build.txt; runtime package distribution metadata and available license files are preserved under _internal. Python license text is included under _internal/licenses/python. The imageio-ffmpeg wheel supplies its upstream FFmpeg binary; upstream wrapper and build/distribution information: https://github.com/imageio/imageio-ffmpeg. Microsoft Edge WebView2 Runtime is a separately installed prerequisite; the pywebview distribution supplies the WebView2 loader/managed assemblies.
