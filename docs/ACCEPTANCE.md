# Check your installation

After installing or updating:

```bash
jvcli --version
jvcli doctor
jvcli login
```

The diagnostic command checks your local setup. It does not prove that every account capability or task will work.

Start in a disposable project with no sensitive files:

```bash
mkdir -p ~/jvcli-tryout
cd ~/jvcli-tryout
jvcli exec --read-only "Describe this directory"
```

An authenticated task can consume service quota. Review the result, then try a small file-editing task and inspect its output yourself. Confirm that the selected permissions match your intention. Use `jvcli sessions` and `jvcli resume SESSION_ID` to check saved work.

Before using the application for important work, test your own workflow and review generated files. Local diagnostics and automated tests are not a guarantee of production acceptance for every workload. Keep a backup of important project files.
