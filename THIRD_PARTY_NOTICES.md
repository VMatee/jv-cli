# Third-party provenance

JV CLI is an independent Python launcher and compatibility adapter around an
unmodified, separately installed Rust agent engine. It is not a complete Rust fork.

The engine is `@openai/codex@0.149.1`, published by the open-source OpenAI Codex
project at https://github.com/openai/codex. The npm package and its platform binary
are downloaded by the installer, not bundled in this archive. Preserve the
upstream license and NOTICE files in `third_party/openai-codex/` and the notices in
the installed npm packages when redistributing an installation.

JV HTTP behavior was independently implemented against the public protocol
examples at https://github.com/VMatee/jv-llm-api-example. This archive does not
vendor the Python, C, C++ or Rust clients from that repository.

The Python runtime, Node.js/npm and other programs on the user's computer have
their own licenses. No font files or user credentials are included.
