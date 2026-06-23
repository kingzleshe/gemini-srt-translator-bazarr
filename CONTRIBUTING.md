# Contributing

Contributions are welcome when they keep the project focused on the core
workflow: Bazarr discovers or extracts English SRT files, this worker translates
them with GeminiSRTTranslator, and Bazarr indexes the generated target subtitles.

## Before Opening a Pull Request

Please include:

- the use case or bug being solved;
- the Bazarr version and deployment style if behavior depends on Bazarr;
- the target language and filename examples when changing language handling;
- tests for behavior changes, queue changes, or path handling changes.

## Development Commands

```bash
python -m unittest discover -s tests -t . -v
python -m py_compile worker.py
```

## Scope

Good fits:

- better Bazarr integration;
- more robust queue behavior;
- safer configuration and deployment docs;
- UI improvements for the existing workflow;
- tests for existing behavior.

Out of scope unless discussed first:

- replacing Bazarr;
- replacing GeminiSRTTranslator with another translation engine;
- installing packages inside the Bazarr container;
- background scanning that constantly walks large media libraries by default.

## Security

Do not include real API keys, media library paths that reveal private data, or
full subtitle files in issues or pull requests.
