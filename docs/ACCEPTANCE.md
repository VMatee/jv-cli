# Acceptance before user rollout

Do not interpret passing tests as a guarantee about every real model, Ubuntu kernel, or production deployment. Record the target checks below for each deployment class.

## 1. Verify installation and offline regressions

Run as your normal user from a trusted clone:

```bash
./verify.sh
./install.sh
$HOME/.local/bin/jvcli --version
$HOME/.local/bin/jvcli doctor --json
./test.sh
```

Expected package version: `0.3.0`. Expected engine: `0.149.1`. `doctor` checks local configuration/version/help, not live authentication or tool execution. `test.sh` uses only loopback mock services and fake engine scripts, not real credentials.

The installer must not require sudo or create a global executable. It creates only the per-user application and launcher paths. It reports a missing `~/.local/bin` PATH entry and changes `~/.bashrc` only with explicit `--add-path`.

## 2. Real-engine contract and sandbox acceptance

```bash
python3 -B scripts/engine_smoke.py
```

This uses the installed **real** engine, a scripted local model, and disposable files under `.state/engine-checks/`. It makes no JV API calls. It checks:

- Actual shell reads return a unique on-disk marker to the next model request.
- A second resumed turn applies a custom patch and changes a real fixture file.
- An attempted outside-workspace write leaves the protected fixture unchanged.
- Read-only mode prevents a workspace write.
- With tool networking disabled, a tool cannot reach the local fixture HTTP server.

The script prints JSON and saves `report.json` in its fixture directory. It exits nonzero on failure. These checks are intentionally conservative: if your environment cannot support them, investigate rather than weakening the sandbox. The tests are not a complete sandbox penetration test.

The script passed against 0.149.1 during release preparation. Keep a fresh report from each Ubuntu deployment class.

It also exercises malformed-response correction after a real shell tool, generic-error recovery, and repeated invalid batches that must fail without executing even their valid member. Optionally pass `--flask-python /absolute/path/to/disposable/venv/bin/python` with Flask already installed to create a small Flask app through the real patch tool and verify its HTML/CSS with Flask's test client. This optional check installs nothing and starts no persistent server. Scripted replies do not establish live-model compatibility.

The default checks also exercise a standalone JSON label followed by a fenced patch, shell call and final response through the real engine. Patch contents and subsequent tool output must retain their literal underscores and quotes. See TEST_REPORT.md for the separate live Flask test and its limits.

## 3. Live API contract

```bash
./jvcli login
python3 -B scripts/live_smoke.py
```

The script identifies the API/user and asks you to type `RUN`. It signs in, uploads its harmless text fixture, polls for success, submits a follow-up using the returned conversation ID, verifies another text response, and attempts logout. It creates two jobs and may consume quota. No passwords are printed or saved.

This checks the API contract, not coding-model ability. Generated files may not be produced by this prompt; their real-server download path needs a separate applicable test. Keep the IDs/status, not credentials, as evidence.

## 4. Real model, real tools, multiple turns

Use a disposable project without private data. Do not test initially against your production repository:

```bash
mkdir -p ~/Desktop/jv-acceptance-project
cd ~/Desktop/jv-acceptance-project
printf 'print("hello")\n' > hello.py
jvcli exec --read-only \
  "Read hello.py, run python3 hello.py, and explain its actual output. Do not modify files."
```

Verify that a local command runs and the final explanation matches the file. Then:

```bash
jvcli
```

First turn: inspect `hello.py`. Second turn: change it to print `Hello from JV CLI`, use the patch tool, run it, and report the output. Check manually:

```bash
cat hello.py
python3 hello.py
```

Run `jvcli sessions`, exit, and resume that JV session in the same directory. Check that a second prompt works without `--color` errors. Check that failed commands produce honest output rather than a false success. Repeat meaningful tasks with the model actually assigned to your account.

## 5. Failure and operational acceptance

Check incorrect credentials, expired tokens where testable, a deliberate failed command, malformed model output if a controlled test backend is available, Ctrl+C while polling, and a reconnect/resume after restart. Do not repeatedly submit ambiguous POSTs to the real service simply to test failure paths; offline tests already exercise them.

For a generated-file-capable account, use direct `ask/job --download-dir` and verify an authenticated download, filename collision handling, file contents, and no execution. For Flask/dependency tasks explicitly enable network, use `.venv`, bind localhost, use a bounded smoke test, and stop the test server. Verify no unwanted global package/profile/system changes.

Test the preserving updater on a copy of the installation, including a failed download with a working runtime present. Check deletion/removal after all tasks and detached services have stopped. Removing the launcher does not undo project edits or delete remote service data.

## Go/no-go record

Record package SHA-256, Ubuntu version, kernel, architecture, Python/Node versions, exact engine version, engine-check report, live-service check result, and actual coding/multi-turn task outcomes. Do not record secrets.

Deploy to a small internal pilot first. Expand only after all applicable checks pass and the remaining limitations are acceptable. No package or test count can guarantee bug-free behavior on every user machine.
