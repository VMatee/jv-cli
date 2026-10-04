# Release engineering

`VERSION` is canonical. New supported platforms use a minor release; corrections
use a patch release. Engine 0.149.1 and protocol 1 are independent pins.
Never modify an existing tag or published release assets.

The release workflow rehearses on `feature/windows-native` and `main`. Linux
builds the normal and offline ZIPs and checks extracted installs. The reusable
Windows workflow builds the existing bundled-runtime ZIP and lowest-privilege
Inno installer, then tests actual installed execution with synthetic services.
No user credentials are needed. All Actions are pinned to exact commit SHAs.

`scripts/release_assets.py` checks each platform inventory, embedded manifests,
version, hashes and source provenance. Assembly rejects mixed commits and emits
one `BUILD-INFO.json` and `SHA256SUMS`. Existing Linux ZIP `.sha256` files remain
public for installer compatibility. All eight public assets are compared after
download; SHA256SUMS covers every other asset. Its own digest is verified against
the generated artifact and GitHub asset inventory. No reproducible-build claim
is made for compiler/installer bytes.

Before merging, require local native/package acceptance and exact feature CI.
Merge without rewriting history. Require exact main regression and package
rehearsal success before tagging. The tag must match VERSION and the accepted
main commit. The single tag-only publisher checks those conditions and refuses
an existing release. It publishes only after both platforms and assembly pass,
then redownloads twice and compares hashes and metadata.

The gate reads Actions metadata. Workflow permissions must include
`contents: read` and `actions: read`; the publish job overrides that set with
`contents: write` and `actions: read`. Keep both scopes explicit and least privilege.

Finally download every public asset into a new disposable directory, verify
inventory/checksums/source, and test the downloaded Windows installer itself.
Installed acceptance includes version/help/doctor, engine discovery, synthetic
auth/turn/resume/cancellation, process ownership, isolated runtime imports,
console/Thai input, same-version reinstall, active-use refusal, failed replacement
rollback, state/PATH boundaries, uninstall and portable extraction. Preserve
unrelated files and leave the final public installation usable. Never inspect
private account/session state. Signing, if later authorized, must happen before
artifact hashing; unsigned Windows artifacts remain explicit.

## Unpublished 0.5.1 tag

`v0.5.1` contains the intended remote support-code functionality, but its tag
workflow stopped at the release gate because the token lacked `actions: read`.
No 0.5.1 GitHub Release assets were published. The tag remains immutable;
0.5.2 carries the same accepted runtime plus corrected workflow permissions.
