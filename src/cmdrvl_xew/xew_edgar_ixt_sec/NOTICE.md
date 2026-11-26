# Vendored: SEC inline XBRL transforms from Arelle/EDGAR

This directory holds third-party code. **Do not edit the two Python files.** `pack` and
`export-facts` refuse to run Arelle if their bytes differ from the hashes below.

| | |
|---|---|
| Source | https://github.com/Arelle/EDGAR, directory `transform/` |
| Commit | `99e94b6c6f5ca2ef06a9c2f29b0a4290a7f959db` (tag `26.1`, 2026-03-13) |
| Taken | `__init__.py` and `text2num.py`, unchanged. Nothing else from `transform/` (not `conf/`, not `transformationRegistry/`). |
| Also copied | the repository's root `LICENSE`, as `LICENSE.EDGAR` |

| File | SHA-256 |
|---|---|
| `__init__.py` | `2296586f945ffd95ab37d3d4147c4e45f42ce4e5f397f61143e053208adefbf1` |
| `text2num.py` | `6c9b26354320a2fb34fe380cdc71ff7f8d1cc712811e6b10c661e512f0383409` |

The identity recorded in packs is `Arelle/EDGAR transform 99e94b6c6f5c sha256:<digest>`, where the
digest is the output of `shasum -a 256 __init__.py text2num.py | shasum -a 256`.

To update: take both files from one upstream commit, update the hashes in `sec_transforms.py`, in
this notice and in `tests/test_sec_transforms.py`, and record an output revision in
`docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD` if any value can change.

## License statements, as found at that commit

The statements below differ from one another. They are recorded here as found. This notice draws no
legal conclusion about which of them applies.

### 1. Repository root `LICENSE`

The file is the text of **CC0 1.0 Universal**. A copy is in `LICENSE.EDGAR`.

### 2. Header of `transform/__init__.py`

> Custom transforms for SEC
>
> Created by staff of the U.S. Securities and Exchange Commission.
> Data and content created by government employees within the scope of their employment
> are not subject to domestic copyright protection. 17 U.S.C. 105.
>
> See COPYRIGHT.md for copyright information.
>
> Local copy of text2num.py was obtained from https://github.com/ghewgill/text2num

No file named `COPYRIGHT.md` was found in the repository at that commit.

### 3. `__pluginInfo__` in `transform/__init__.py`

```python
    'license': 'Apache-2',
    'author': f'SEC employees (integrated by {authorLabel})',
    'copyright': f'{copyrightLabel} \nUtilizes text2num.py (c) 2008 Greg Hewgill',
```

`authorLabel` and `copyrightLabel` are imported from the installed Arelle (`arelle.Version`).

### 4. Header of `text2num.py` (MIT License)

> This library is a simple implementation of a function to convert textual
> numbers written in English into their integer representations.
>
> This code is open source according to the MIT License as follows.
>
> Copyright (c) 2008 Greg Hewgill
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
> THE SOFTWARE.
>
> HF: 2019-02-07 modified word split pattern for transformation dash pattern
