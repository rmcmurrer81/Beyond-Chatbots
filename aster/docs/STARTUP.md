# Optional Windows logon startup

This is **source-only opt-in support**. Nothing has been installed on the user's
computer or registered in the development or CI machine's startup settings.
The default command is a read-only plan. Enabling persistent startup requires an
explicit, fresh owner decision after reviewing the exact plan in an interactive
terminal. Merely opening the desktop or running a test does not enable it.

## What it means after a restart

Once the owner has explicitly enabled it on their Windows computer, Aster can
open at that Windows user's next **sign-in**. Windows may delay startup apps.
This does not start before sign-in, unlock the computer, or turn the hardware on.
After a power outage, the computer must boot and the owner must sign in normally.
No BIOS/power-recovery settings, automatic login, saved credentials, Windows
service, scheduled task, administrator access, or machine-wide setting is used.
Aster still needs a graphical Windows session and a working Python/Tk install.

The launcher opens the local desktop through `lifecycle.startup_launch(state)`.
The desktop acquires its existing state lock before lifecycle recovery starts;
a second process cannot own the same state. Lifecycle recovery preserves identity
and memory and identifies interrupted operations. It does not invent a NewBrain
answer or replay a previously running job. NewBrain remains unavailable until a
real, qualified local runtime is provided.

## Review on the owner's computer

Use the stable, non-OneDrive, owner-controlled state directory already used by
Aster. The directory must exist. If this is the first run, a normal Aster status
command can initialize it before startup is reviewed.

```powershell
$state = Join-Path $env:LOCALAPPDATA 'Aster\state'
python -m aster --state $state status
python -m aster --state $state startup
python -m aster --state $state startup status
```

`startup` defaults to a dry-run enable plan. It identifies:

- The currently running Python executable, resolved to an absolute path
- This checkout's fixed `launch_aster.py`, its hash, and the absolute state path
- Every Python argument and the exact Windows command line
- The current-user registry key, exact owned value name, and value type
- Any existing registration, ownership conflict, and the plan digest

Copy the `plan_digest` from the reviewed enable plan. The owner may then request
`startup enable --plan-digest DIGEST` and review the fresh interactive
confirmation. `startup disable` requires its own disable plan digest, review, and
confirmation.
There is no unattended `--yes` or `--approve` switch. These commands must not be
run by an assistant against a real computer without the owner's action-time
approval for that exact persistent change. Dry-run planning and status alone do
not grant that approval.

```powershell
python -m aster --state $state startup enable --plan-digest ENABLE_PLAN_DIGEST
python -m aster --state $state startup plan --action disable
python -m aster --state $state startup disable --plan-digest DISABLE_PLAN_DIGEST
```

Check `python -m aster startup --help` for the current CLI options. The Python
API requires `reviewed_plan_digest` and a confirmation callback that receives
the exact current plan and returns literal `True`; the production CLI requires
an interactive terminal and a newly entered confirmation phrase. A changed plan
must be reviewed again. Nothing executes a user-supplied module or executable.

## Exact registration and safe removal

Only one value under this key is in scope:

```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
```

Its name is `AsterWorkstation-` followed by a digest of the absolute state path.
It stores a `REG_SZ` command for the fixed launcher with Python `-I -S -B`:
isolated imports, no site initialization, and no bytecode output. The launcher
explicitly pins imports to its own verified checkout. The login working directory,
`PYTHONPATH`, user site packages, command shells, and PowerShell are not used.
Paths containing environment-expansion tokens, controls, reparse points, or
ambiguous Windows aliases are refused. The exact command is bounded to 260 UTF-16
units; long paths produce an error, never a truncated command. Use shorter private
paths if needed.

A bounded ownership receipt, `startup-registration.json` in the selected state,
records the exact command before registration. The helper refuses to overwrite
any existing unowned value, even if it happens to contain the same command.
Disable removes only a value whose name, type, and contents exactly match the
owned receipt. It does not remove the registry key or restore a snapshot of other
programs' settings. Unrelated startup entries remain untouched.

If another tool modifies the owned value or the ownership receipt is invalid,
the helper stops and preserves the value for inspection. Keep the receipt and
state directory private. Do not delete the receipt to resolve a conflict: doing
so intentionally makes an existing value unowned, which the helper will refuse
to remove. A changed checkout/launcher plan must first be disabled using its old
receipt, then enabled after a fresh review. The old owned entry can still be
removed if the launcher was moved or deleted.

A failed or interrupted registration may leave a `pending_or_missing` receipt.
Review status, then explicitly retry enable or disable to clean up that receipt.
If registry access is denied, the helper reports the error instead of requesting
administrator access or trying another persistence mechanism.

The advisory registration lock coordinates cooperating Aster processes. Registry
values are checked again immediately before mutation and after confirmation;
these checks are not an atomic compare-and-swap against hostile programs running
as the same Windows user. This is trusted-owner local storage, matching Aster's
existing state threat model. It does not promise sudden-power-loss durability or
prevent an administrator or another same-user program from changing startup.

## Validation boundaries

`tests/test_startup.py` uses only fake registry backends and a fake `winreg` module.
A tripwire prevents accidental real-registry access in those tests. Coverage
includes read-only plans, explicit cancellation, stale approvals, conflicting or
modified values, interrupted registration, exact disable, unsafe paths, corrupt
receipts, and isolated imports from an unrelated working directory. The Windows
CI-only parser test round-trips quoted arguments through native
`CommandLineToArgvW`; it never reads or changes startup settings. Parser tests on
non-Windows are skipped rather than described as native Windows validation.
A real user's logon launch has not been verified by these tests.

Microsoft documents the sign-in trigger and Run-value command-length limit in
[Run and RunOnce registry keys](https://learn.microsoft.com/windows/win32/setupapi/run-and-runonce-registry-keys).
