---
title: Terms
layout: default
permalink: /terms/
---

# Terms

## Software and documentation

New code and documentation in this project are provided under the [MIT License](https://github.com/SecurityRonin/MPI3508/blob/main/LICENSE), copyright Security Ronin Ltd. External projects linked here retain their own licences; a source citation does not relicense their code or imply endorsement.

The software is supplied “as is”, without warranty, as stated in the MIT License. The documentation describes a narrow reference profile, not a guarantee of compatibility or physical accuracy.

## Scope and operational risk

The profile targets touchscreen configuration on Raspberry Pi 5 / Kali arm64 / Xorg-libinput. It does not set up the display or certify the hardware. A fit recorded on one panel may be inaccurate on another unit.

Privileged changes to boot and Xorg configuration can affect input availability. Preserve independent recovery access and review the preview before installation. Backups are a recovery mechanism, not a guarantee that restoration will be safe after later changes. Drift-safe refusal is intentional.

Saved-file checks, runtime readback and physical stylus accuracy are distinct. Automated verification cannot substitute for a physical test. The [validation record](https://securityronin.github.io/MPI3508/validation) states the evidence available for this project.

[Guide](https://securityronin.github.io/MPI3508/) · [Privacy](https://securityronin.github.io/MPI3508/privacy)  
© Security Ronin Ltd
