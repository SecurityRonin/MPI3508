# Reference fixture

## `reference-profile.json`

| Field | Recorded provenance |
|---|---|
| Identity | `pi5-kali-reference`: one MPI3508 panel on Raspberry Pi 5 / Kali arm64 / Xorg-libinput; supplied 6 October 2026. |
| Source | The user’s measured panel configuration, reproduced from an existing private status record. This is recorded configuration, not newly collected hardware measurements or a vendor preset. Private source linkage stays outside this repository. |
| Original download URL | Not applicable: supplied from the user’s setup, not downloaded. |
| Contents | Nine full-precision matrix values, X/Y ABS endpoint pairs of 200–3900, profile identity, normalization description and scope caveat. Recorded startup/property readback, not fresh physical edge acceptance. |
| SHA256 | `08049461b5a0e5306cf99c7b5202824d00805ea31e63efceb080747a8f8a07f9` |
| MD5 | `ed3f7f0bd85870f4211d661d47e5aa8b` |
| Publication and licence | The numeric configuration is reproduced under the user’s explicit request to publish it. Newly authored project code and the JSON wrapper are under the repository’s [MIT License](../../LICENSE). No vendor installer, kernel code, raw contacts or private calibration evidence is redistributed or relicensed here. |
| Use case | `tests/helpers.py::reference` loads this JSON; `tests/test_planning.py` checks the generated Xorg matrix against its nine recorded values. This tests transcription fidelity, not physical accuracy. |

The reference JSON is recorded real configuration. Temporary boot/Xorg trees and failure-injection inputs constructed by the tests are synthetic installer-mechanics fixtures. Neither is an independent physical calibration oracle. The new installer has not been applied to the source panel.

`.gitattributes` marks `tests/data/**` as `-text` to preserve committed fixture bytes across Git checkouts.
