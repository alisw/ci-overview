## CI Status Overview

This package provides a CLI script and a basic webserver, both of which give an overview of the ALICE CI system -- which pull requests have been tested, whether they succeeded or not, for each defined check.

### Installation

```bash
python3 -m pip install 'git+https://github.com/alisw/ci-overview@master'
```

### Running

Run one of the installed scripts created by the installation step above:

- `alice-ci-overview` in your terminal, or
- `alice-ci-overview-http` to start a webserver.
