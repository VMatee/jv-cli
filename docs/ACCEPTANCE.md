# Check your installation

After installing or updating:

```bash
jvcli --version
jvcli doctor
```

The diagnostic command checks your local setup. It does not prove that every account capability or task will work.

Only when you intend to contact your configured service, run `jvcli login`. Authentication contacts that service; authenticated tasks can consume quota. Local diagnostics alone do not require a production task.

On Linux, start in a disposable project with no sensitive files:

```bash
mkdir -p ~/jvcli-tryout
cd ~/jvcli-tryout
jvcli exec --read-only "Describe this directory"
```

On Windows, use an ordinary-user dedicated worker PC and follow [Windows installation](WINDOWS_INSTALL.md). Native execution requires explicit `--execution-mode trusted-host`; the Linux read-only example above is unsupported. Tools have full host filesystem and network access, so a disposable project alone does not isolate the host. First check `jvcli.exe --version` and `jvcli.exe doctor`; authorize any live task separately.

An authenticated task can consume service quota. Review the result, then try a small file-editing task and inspect its output yourself. Confirm that the selected permissions match your intention. Use `jvcli sessions` and `jvcli resume SESSION_ID` to check saved work.

Before using the application for important work, test your own workflow and review generated files. Local diagnostics and automated tests are not a guarantee of production acceptance for every workload. Keep a backup of important project files.
