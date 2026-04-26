# Phase 2 Handoff Note — CD Dragon Anim Retarget

**Status:** Phase 0+1 plan complete. **Phase 1 kill criterion fired.** JMM's overlay PAZ mechanism does not reach the engine's animation load path — overrides for `.paa` files have zero in-game effect even when JMM successfully writes the overlay and updates `meta/0.papgt`.

This note exists so the next brainstorming session knows exactly what was confirmed and what's still unknown for Phase 2.

## What we proved (high confidence)

### Animation system architecture
- CD's animation clips are `.paa` files (Pearl Abyss proprietary format), NOT `.hkx` as the spec assumed.
- Magic bytes: ASCII `PAR ` (0x50 0x41 0x52 0x20). Likely "Pearl Abyss aRchive" or similar.
- 74 dragon-specific clips at `0009/20.paz`, fully descriptive filenames (`cd_dragon_basic_01_00_air_stand_hover_idle_00.paa`).
- Two-tier wrapping: full-detail clips (12–120 KB) have a 2-byte `0xf0 0x03` prefix before `PAR `; LOD variants (1.5–2.2 KB) start cleanly with `PAR `. The prefix appears to be a chunk/compression wrapper specific to non-LOD clips.
- Companion formats: `.paa_metabin` (action chart sidecars, 87 dragon entries in `0010/0.paz`) and `.motionblending` (motion blending graphs, 323 entries in `0009/0.paz`). Their roles in the load path are unknown.

### VFS layout for dragon anims
- Full path: `character/motion/2_mon/cd_m0004_00_dragon/cd_m0004_00_dragon/00_mon/<clip>.paa`
- JMM auto-resolves a flat `files/<filename>` mod input to this deep path during apply.

### JMM mechanism (independent of anim outcome)
- JMM does NOT patch vanilla PAZs. It writes new overlay PAZs into a fresh group (`0036/0.paz`) and updates `meta/0.papgt` (master VFS routing table) atomically.
- For mesh PAC, cooked PAB, textures (DDS) — overlays DO take effect (V11 ships fine via this path).
- For anim `.paa` — overlays appear to be IGNORED by the engine. This is the kill finding.

### What we ruled out via Test C
- It's not byte-corruption-in-transit (Test A: byte-identical clone produced byte-identical behaviour).
- It's not magic-byte-validation-fallback (Test C: a complete valid `.paa` from a different clip ALSO produced no change — engine is not "validating then falling back to vanilla").
- It's not a wrong-clip-state-mapping (the user observed the hover-idle state for all three tests; Test A's identical-anim PASS is proof we were watching the right state).
- It's not an apply-skip (user re-clicked Apply between Tests B and C).

## What this means for Phase 2

The straightforward "drop a `.paa` into a JMM mod folder" approach is dead. Whatever anim-injection mechanism we build must operate at a layer JMM does not currently reach. Candidate hypotheses for why JMM doesn't work, in rough order of likelihood:

1. **Anim clips are batch-loaded into memory at game launch** (single read from vanilla PAZ, then never re-read from disk). JMM's overlay change to `meta/0.papgt` doesn't matter because the engine isn't doing further VFS lookups for anims after startup.
2. **`.motionblending` graphs reference clips by an internal hash or absolute resource ID**, not by VFS path — so changing the VFS lookup doesn't change which clip data the engine fetches.
3. **The engine has a separate anim-routing layer** (parallel to `meta/0.papgt`) that JMM doesn't update. Possibly buried in the `.papgt` infrastructure but addressed by a sub-key only the anim subsystem reads.
4. **Anim PAZ has its own integrity / checksum table** that the engine consults before honoring overlay redirects. JMM's overlay doesn't have a corresponding checksum entry, so the engine silently rejects it.

## Open questions for Phase 2 brainstorm

- Which of the four hypotheses above is correct? (Static vs dynamic anim load is the cheapest to test next.)
- Is there a way to invalidate the engine's anim cache mid-session, OR force a re-read?
- What does `.papgt` actually contain? Are there per-asset-type sections, and is anim a separate section?
- Can `.motionblending` graphs be modded? They're loaded via the VFS we know works — modding the graph is potentially a way to redirect clip references.
- Does `.paa_metabin` need to be modded in lockstep with `.paa`? If yes, that explains why our `.paa`-only override is rejected.
- Could we patch the vanilla `0009/20.paz` directly (not via JMM overlay) to test whether the engine reads from the original file post-launch? This would be destructive, requires backup, but cheaply differentiates "JMM-overlay-broken" from "engine-doesn't-re-read".
- What's the binary internal format of `.paa` (beyond magic + 2-byte prefix)? Phase 2 decode is unaffected by Phase 1 kill — it can proceed in parallel and is required regardless of injection mechanism.

## Recommended Phase 2 framing

The next brainstorm should split the project into two independent sub-projects:

**Sub-project A — Anim injection mechanism.** Goal: find ANY way to make a modified anim clip play in-game. Hypothesis-test the four candidates above. Possibly involves: in-place patching of vanilla `0009/20.paz`, modding `.motionblending`, runtime memory injection, or executable patching. Until one of these works, the rest of the project is academic.

**Sub-project B — `.paa` format decode.** Goal: round-trip a vanilla `.paa` byte-exact. Independent of A — required regardless of how we inject. Pearl Abyss proprietary format, no community tooling exists, this is from-scratch RE work. Likely months.

A and B both need to succeed before any custom-anim ships in-game. They can run in parallel.

## What's preserved from Phase 0+1

Code:
- `tools/anim/paz_listing.py` — PAMT-based PAZ content lister (works against any CD PAZ archive)
- `tools/anim/find_anim_paz.py` — keyword-scoring scanner across all 174 PAZs
- `tools/anim/extract_anim_paz.py` — extracts files from a candidates JSON to disk
- `tests/anim/test_paz_listing.py` — round-trip test against the mesh PAZ

Artifacts:
- `dragon-anim-candidates.json` — ranked candidate list, 29 PAZs with dragon hits, top-scorer is `0009/20.paz`
- `dragon-anim-extract/character/` — 915 extracted anim files including 174 dragon-specific (gitignored, regenerable)
- 74 full-detail `cd_dragon_basic_*.paa` clips with descriptive state names ready for analysis

Knowledge captured in `docs/cd_anim_format_notes.md`:
- PAZ/PAMT binary format
- Anim VFS path layout
- `.paa` magic and two-tier wrapping pattern
- JMM apply-time mechanism (overlay PAZ + papgt update)
- Phase 1 kill verdict + interpretation

## Resume instructions

When picking this up:
1. Read `docs/cd_anim_format_notes.md` for the running findings (it's the source of truth, not this handoff note).
2. Decide whether to start with Sub-project A (injection) or B (decode), or both.
3. Run a fresh `/superpowers:brainstorming` session with this handoff loaded as context.
4. Write the new spec(s) and plan(s) against the resulting decisions.

The Phase 0+1 worktree (`feat-anim-retarget` branch) can either be merged to master (it produced shippable tooling that future work will use) or kept as a research branch and built on. Tooling reuse is the strongest argument for merging.
