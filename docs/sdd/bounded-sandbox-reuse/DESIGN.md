# Protected generations and bounded sandbox reuse

Date: 2026-11-11. Status: implementation present; qualification is incomplete.
The performance comparison and remaining consumer/resource checks must pass
before this work can be called complete.

This supersedes the SquashFS prerequisite in the
[historical feasibility gate](../immutable-runtime-standby/DESIGN.md). The OS,
kernel, launch tools, host loader and root-managed installation are trusted.
Ordinary-user runtime modification and malicious image inputs remain inside the
boundary. Root/kernel compromise and hostile modification of the calling process
are outside it. Historical findings and transaction measurements remain historical.

## Installation and validation

The umbrella manages `runtime/current`, a root-owned regular selector containing
one lowercase SHA-256 basename and a newline, and `runtime/generations/<id>`.
Identity is SHA-256 over `holonight-images-policy-1\n` followed by the exact
manifest bytes. Each generation has at most 128 regular files and 128 MiB,
including its manifest. Complete inventory, required plugins, modes, sizes and
hashes are checked; symlinks and unexpected entries are rejected.

`scripts/manage-images-generations.py` in the umbrella copies through no-follow
descriptors into fresh root-owned staging. It validates the complete copy before
`renameat2(RENAME_NOREPLACE)` publication. It never overwrites a generation or
changes ownership to adopt source inodes. Old source descriptors and writable
aliases therefore cannot mutate published copies. Every generation entry and
ancestor through `/` must be root-owned without group/other write permission.

One current and one retired generation are retained. An eligible retired
generation must be removed under a nonblocking exclusive directory `flock`
before staging a third. A busy lease rejects the upgrade before selection changes.
Rollback selects an already owned and validated retained generation. Selection is
published by atomic replacement of the regular `current` file.

The umbrella's generic copy/removal loops exclude managed contents. Ownership
records include both generations and management files. A separate operation lock
spans installation/removal through umbrella ownership publication; the runtime
lock serializes generation operations. Empty lock/ownership bookkeeping is
intentionally retained by uninstall so a waiting process cannot acquire an old
lock inode while a new installer creates a different one. Modified, unowned and
busy payloads retain their records and are reported.

Initial legacy conversion requires `--maintenance-migrate-images-runtime` on the
umbrella installer. **All image-consuming applications must be stopped first.**
Legacy ownership, modes and bytes are checked against umbrella records. The
copied legacy inventory is checked again, then an atomic directory exchange
publishes the managed layout. A late legacy conflict preserves its backup.
Subsequent upgrades use generation leases and support live workers.

System installation selects managed generations. Alternate staging roots opt in
with `--protected-images-runtime` and require protected ancestors. Ordinary CMake
staging/relocation and mutable alternate roots keep the raw bundle layout and
full validation on every one-shot call. No host deployment is part of qualification.

## Owner and lease contract

`RuntimeOwner` synchronously selects and validates an epoch. `acquire()` shares a
validated `GenerationLease`; its copies hold the same shared directory lease.
Acquisition opens without following symlinks, locks before inventory validation,
and rechecks selector inode/content and generation directory identity before
acceptance. The published tree is not mutable while this proof is reused.

`refresh()` revokes acquisitions before validation. Failure has no stale fallback.
An active transaction can finish using its original lease. Owner refresh/acquire
are synchronized; workers share immutable validation results rather than rehashing
libraries. A cleanup failure permanently disables this owner, including across
refresh. Directory leases survive workers until verified cleanup.

Preparation records `sessionProtocol`, probed from the copied trusted helper's
no-image capability command. Missing/zero means legacy one-shot execution; one
permits session negotiation. Unsupported values fail validation. Retained legacy
generations remain usable for one-shot rollback; they are never silently treated
as session-capable. A capability declaration alone does not prove readiness.

`IsolatedClient(QString)` resolves managed layouts and holds leases through exit
and cleanup. The lease constructor reuses owner validation. Direct mutable bundle
calls continue full per-call validation. One-shot success retains exit-before-
success and verified hierarchical cleanup semantics.

## Reusable mechanism

`ReusableSession` is move-only, synchronous and caller-owned. Preparation, use,
retirement and destruction stay on its preparing thread. Images owns mechanisms;
[File Browser](../../../../holonight-file-browser/docs/sdd/responsive-previews/DESIGN.md)
owns threads, scheduling, cache and recycling policy. Thumbnails continues borrowing
`SourceTransaction` and never owns worker lifetime.

One-shot and reusable calls share launch, exchange validation and exactly-once
retirement. Preparation checks the actual 2-GiB memory and zero-swap cgroup limits
before releasing the trusted host-loader gate. Namespace restrictions, fixed codec
inventory, raw-pixel validation and input/output ceilings remain unchanged.
Startup and each active transaction have separate 15-second deadlines; cleanup
retains five seconds. Blocking caller-device reads and mutable runtime hashing
remain outside those interruptible deadlines.

Readiness negotiates session protocol version one. Commands/replies carry a
transaction identity and sequence; completion has its own strict command/identity/
sequence acknowledgement. Each scoped helper transaction starts with inspection,
allows at most four cached PNG attempts and one retained-source decode, then
destroys source bytes, devices, readers, pixels and provisional output before
acknowledging completion. Counters reset for each transaction.

`SessionResult` is distinct from `IsolatedResult`. Its successful boolean test
requires a validated reply and completion acknowledgement from a living helper;
it does **not** prove terminal cleanup. Local source/limit rejection has no
acknowledgement and preserves readiness. Cancellation before dispatch also
preserves readiness. Dispatched cancellation, malformed/mismatched responses,
crashes, callback exceptions and deadlines poison and retire the session.
Unsolicited idle output closes the read side and retires the worker, preventing
unbounded growth of the parent's Qt buffer. Idle exit also poisons readiness.

A transaction-start callback fires only after the first command is accepted for
wire dispatch. Consumers use this boundary for standby preparation and counting
started transactions; cache hits and local rejection do not manufacture starts.

Unsuccessful cleanup disables the owner. The launcher object and its lease enter
a process-held quarantine until process exit. They are deliberately not destroyed,
retried or sent through manager cleanup again: a running `QProcess` destructor
would otherwise add a kill/wait outside the cleanup budget. Unverified generations
remain pinned. Process exit releases the process-held locks.

**Worker compromise may persist across successful transactions until recycling.**
An acknowledgement proves transaction-local lifetime and protocol validation, not
that a previously exploited codec has become trustworthy again.

Once launch has started, cancellation waits for scope identity before retirement.
The trusted gate cannot consume image input during that interval, and the startup
deadline still applies. This avoids an unprovable cleanup race with scope creation.

## Verification and assessment

Deterministic protocol/helper tests cover repeated requests, candidate/source
limits, identity/sequence rejection and completion framing. Owner fixtures cover
protected ancestry, shared/exclusive leases, refresh revocation, capabilities and
permanent owner disable. Native session fixtures additionally exercise source
isolation, pre-dispatch cancellation, dispatched cancellation, callback failure,
idle output/exit, descendants, deadlines and cleanup-failure lease retention.

Privileged umbrella scripts use disposable `/run` roots for fresh-copy publication,
ordinary-user writes, busy upgrades, rollback, legacy conversion and conservative
installer/uninstaller delegation. Provider and installed-package checks remain
required. Evidence belongs under the ignored umbrella
`build/preview-reuse-dgi4528s`; historical evidence is unchanged.

The new `tooling/preview-benchmark/reuse.cpp` and
`scripts/measure-preview-reuse.py` preserve pixels and metadata separately,
incorrect/missing observations, explicit readiness, constructor startup, recycling,
cancellation depletion and navigation at 0/25/100/250 ms. Smoke runs cannot qualify.
The frozen comparison requires 100 samples per fixture/scenario/variant, separate
warm-ups and alternating blocks of ten. Targets and every lifecycle/resource/
consumer gate remain mandatory; no low-end hardware qualification is claimed.
See the [umbrella assessment](../../../../docs/initiatives/immutable-runtime-standby.md).


The completed 100-sample-per-case run has 4,000 successful protected one-shot
observations and 4,000 successful reusable observations. All calculated numerical
gates pass. The original transaction baseline has eight cleanup-flagged entries
and 17 missing placeholders in navigation, so its affected quantiles are partial
and strict qualification remains incomplete. See the umbrella assessment for
absolute/percentage comparisons, retained failures and final native/package checks.
