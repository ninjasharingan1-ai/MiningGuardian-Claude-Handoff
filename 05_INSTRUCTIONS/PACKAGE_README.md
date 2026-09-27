# MiningGuardian Claude Handoff Package

This package intentionally keeps project surfaces separate.

## 01_FULL_HISTORICAL_PROJECT

A filtered copy of the historical/development MiningGuardian root.

Use this for forensic reconstruction of M0/M1/M2 and later evolution.

Do NOT treat it automatically as the active continuation source.

## 02_ACTIVE_CURRENT_WORKTREE

The accepted active M3.2 S4A continuation worktree.

Current expected accepted checkpoint:

`97b9837068f553085cc066a4134d165cb1a9c40c`

This is the tree from which implementation should continue only AFTER the full forensic takeover passes.

## 03_ACCEPTED_BASELINES

Contains:

- accepted M2 FINAL archive;
- extracted M2 FINAL contents;
- accepted M3.1 FINAL FREEZE archive;
- extracted M3.1 FINAL FREEZE contents;
- critical authority / acceptance documents.

Archives are retained so their original hashes can be verified.
Extracted copies exist so nested ZIP support is not required.

## 04_FORENSICS

Contains:

- Git identity / status / history reports;
- tracked-file inventories;
- file-tree inventories;
- portable Git bundles where creation succeeded;
- archive inventory with SHA-256;
- current accepted checkpoint evidence.

## 05_INSTRUCTIONS

This README and handoff notes.

# Mandatory takeover rule

DO NOT merge the historical project, active worktree, or frozen baselines automatically.

First reconstruct:

historical implementation
→ accepted M2
→ accepted M3.1
→ M3.2 S1/S2/S3/S4 evolution
→ current R4 checkpoint

Only then continue S4A-R5.

If any expected accepted hash disagrees with the package contents, STOP and report the mismatch.
