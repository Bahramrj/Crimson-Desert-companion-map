# Third-party notices for `gamedata/`

The archive reader (`archive.py`) is our own code. The knowledge of the archive format it
implements (PAMT index layout, ChaCha20 key derivation from the file name, LZ4 block
compression, and "partial DDS" headers in `meta/0.pathc`) comes from these MIT-licensed
projects:

- **CrimsonDesertModdingTools** by NattKh, MIT License.
  https://github.com/NattKh/CrimsonDesertModdingTools
- **CDMW Archive Lite** (`native/cdmw_archive_core`), Copyright (c) 2026 CDMW, MIT License.
  https://github.com/Ratty123/CDMW-Lite

The lookup3 hash is Bob Jenkins' public-domain `hashlittle`.

MIT License text (applies to the projects above):

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software
> and associated documentation files (the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
> BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
> DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

No game files are part of this repository or the app. The importer reads the user's own
install at run time and writes only to the local asset store.
