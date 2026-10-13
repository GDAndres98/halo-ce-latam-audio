# Migration `radio_preset` (20261013T120636_radio_preset)

Owner-authorized (2026-10-13): Spain radio filter on the pilot-style radio lines; approved audio set to needs rework. Mode: **write**.

- Preset: `{"low_hz": 700, "high_hz": 3300, "slope_db_oct": 36, "presence_db": 0, "drive_db": 0, "noise_dbfs": null, "preset": "spain"}`
- Changed: **40**; skipped: 0.
- File before: `2956034fcf13a3a72842d87398a8ba65a106d9bb274421f5d633ac2dfa39790d`; after: `95e8be510cfd659a2e68411056a646f2b578ced2182ed41706d0c1bf84cc6cf6`

| Mapping | Slot | Audio before → after | Recipe |
|---|---|---|---|
| `m-000054` | `es:A10_643_cortana#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000119` | `es:sgt05g#0` | approved → needs_rework (rev 5) | 2 cuts (0.63 s) · radio spain 700–3300 Hz |
| `m-000176` | `es:lif_01#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000177` | `es:lif_02#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000178` | `es:lif_04#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000179` | `es:lif_05#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000481` | `es:C10_200_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000482` | `es:c10_010_captpilot#0` | approved → needs_rework (rev 2) | trim 0.00/0.11 s · 2 cuts (0.46 s) · fades 0/10 ms · radio spain 700–3300 Hz |
| `m-000487` | `es:C10_extract_050_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000488` | `es:C10_insert_030_Pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000489` | `es:C10_insert_040_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000490` | `es:B40_insert_020_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000491` | `es:C10_insert_050_pilot#0` | approved → needs_rework (rev 2) | trim 0.00/1.71 s · fades 0/10 ms · radio spain 700–3300 Hz |
| `m-000492` | `es:C10_230_pilot#0` | draft → draft (rev 1) | radio spain 700–3300 Hz |
| `m-000507` | `es:D40_410_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000508` | `es:D40_411_Pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000510` | `es:B40_040_bisenti#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000536` | `es:B30_350_pilot%202#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000537` | `es:B30_020_bisenti#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000539` | `es:A30_1030_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000558` | `es:A30_1040_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000560` | `es:A30_insert_020_LifeboatPilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000563` | `es:A30_EXTRACT_050_PILOT#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000566` | `es:A30_EXTRACT_020_PILOT#0` | approved → needs_rework (rev 2) | 1 cut (0.31 s) · radio spain 700–3300 Hz |
| `m-000568` | `es:A30_990_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000569` | `es:A30_980_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000570` | `es:A30_970_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000572` | `es:A30_930_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000574` | `es:A30_1080_pilot#0` | approved → needs_rework (rev 2) | 1 cut (0.29 s) · radio spain 700–3300 Hz |
| `m-000575` | `es:A30_250_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000576` | `es:A30_261_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000577` | `es:A30_300_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000578` | `es:A30_340_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000579` | `es:A30_350_pilot#0` | approved → needs_rework (rev 2) | 1 cut (0.57 s) · +1 silence (0.20 s) · radio spain 700–3300 Hz |
| `m-000580` | `es:A30_370_pilot#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000585` | `es:A30_210_bisenti#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000586` | `es:A30_220_bisenti#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000588` | `es:A30_720_Bisenti#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000597` | `es:A30_720_Mendoza#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |
| `m-000647` | `es:A50_710_bisenti#0` | approved → needs_rework (rev 2) | radio spain 700–3300 Hz |

## Verification

- written_sha_matches: True
- result_equals_plan: True
- only_audio_of_targets_changed: True
- every_target_has_the_filter: True
- none_left_approved: True
- idempotent_second_pass_changes_nothing: True
