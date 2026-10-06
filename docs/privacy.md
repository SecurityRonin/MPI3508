---
title: Privacy
layout: default
permalink: /privacy/
---

# Privacy

## Local operation

The pinned `mpi3508.py` candidate is a local touchscreen-configuration tool. Source inspection found no network-request or telemetry implementation: its external runtime command is the local `xinput` query. It requires no account or personal information to select a reference profile. This is a source-review finding, not an exhaustive network-traffic measurement.

The documentation’s downloader separately contacts GitHub without root privileges. The elevated verifier checks and executes the downloaded bytes without making a network request.

Backups, locks and transaction journals stay in the root-owned `/var/lib/mpi3508` state directory. Backups contain the original configuration bytes; journals contain target paths, identities, hashes, transaction lineage and recovery state. Configuration may contain system-specific information. The verifier reads relevant device-tree/input properties and a current Xorg log; it reports check outcomes rather than publishing the log, full environments or authentication files.

## Website and external services

The documentation is configured for GitHub Pages; deployment is not yet verified. Visiting the hosted site, downloading source, viewing a badge or following a sponsor link involves external services. GitHub’s privacy statement describes service-usage information including IP addresses and request times, and logged website interactions: <https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement>. Hosting therefore has a different privacy boundary from the local installer.

This project’s documentation configuration adds no analytics or tracking scripts. GitHub, Shields.io badges and sponsor destinations apply their own policies; local operation is not a claim that those services keep no logs.

Issues and pull requests are public when the repository is public. Share the relevant diagnostic result and configuration fragment, not unredacted journals, private paths, hostnames, addresses, credentials or full logs.

[Guide](https://securityronin.github.io/MPI3508/) · [Terms](https://securityronin.github.io/MPI3508/terms)  
© Security Ronin Ltd
