# Vendored adapter snapshots

Upstream: https://github.com/fanyuantaier/wechatauto-replica

License: Apache-2.0 (see LICENSE).

The three Python files are retained verbatim from the previously reviewed working deployment. SOURCES.json records SHA-256 hashes; no release tag or upstream commit is asserted without verification.

The application does not import the entire automation package. `wechat_backend.py`, `native_access.py` and `media_context.py` load explicitly selected helpers. Changes to these snapshots must be reviewed and regression-tested: several selectors depend on source structure and WeChat internals. Do not replace them with unpinned downloads at startup.

These files contain generic adapter code, not any user's database, credentials, chat history or media.
